import os
import json
import ssl
import time
import logging
import threading
import subprocess
import concurrent.futures
from flask import Flask, jsonify
from flask_cors import CORS
from flasgger import Swagger, swag_from
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# -------------------------
# Flask & Swagger Setup
# -------------------------
app = Flask(__name__)
swagger = Swagger(app)
CORS(app)

# -------------------------
# Logging Configuration
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('vm_monitor_api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ESXiMonitorAPI")

# -------------------------
# Configuration
# -------------------------
# Note: Host, User, and Pass are loaded dynamically from servers.local.json
PORT = int(os.getenv("ESXI_PORT", 443))
WARNING_THRESHOLD = 25
CRITICAL_THRESHOLD = 15
CPU_HIGH_THRESHOLD = 80
CPU_MID_THRESHOLD = 40
POLL_INTERVAL_SECONDS = 30

# -------------------------
# Global Multi-Host Cache
# -------------------------
GLOBAL_CACHE = {}
CACHE_LOCK = threading.Lock()

# -------------------------
# Helper Functions
# -------------------------
def load_servers():
    """Reads the ESXi credentials from the local JSON configuration file."""
    config_path = os.path.join(os.path.dirname(__file__), 'servers.local.json')
    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found at {config_path}")
        return []
    with open(config_path, 'r') as f:
        return json.load(f)
    
def _dedupe_preserve_order(items):
    seen = set()
    out = []
    for it in items:
        if it is None:
            continue
        key = str(it).strip()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out

def _normalize_cpu(raw_val):
    if raw_val is None: return None, 0.0
    try: r = float(raw_val)
    except Exception: return raw_val, 0.0

    cpu_percent = 0.0
    ar = abs(r)
    if 0 < ar < 1: cpu_percent = r * 100.0
    elif 1 <= ar <= 100: cpu_percent = r
    elif 100 < ar <= 10000: cpu_percent = r / 100.0
    else:
        if ar > 10000: cpu_percent = r / 100.0
        else: cpu_percent = r

    try:
        if cpu_percent < 0: cpu_percent = 0.0
        if cpu_percent > 100: cpu_percent = 100.0
    except Exception:
        cpu_percent = 0.0

    return r, round(cpu_percent, 2)

def external_alert(message):
    logger.warning(f"*** ALERT TRIGGERED: {message} ***")

# -------------------------
# Single Host Monitor Class
# -------------------------
class ESXiMonitor:
    """Manages the connection and metrics for a SINGLE ESXi server."""
    def __init__(self, server_id, name, host, user, password, port=443):
        self.server_id = server_id
        self.name = name
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.si = None
        self.cpu_counter_id = None

    def _get_connection(self):
        if self.si:
            try:
                self.si.CurrentTime()
                return self.si
            except Exception:
                logger.warning(f"[{self.name}] Session expired. Reconnecting...")
                self._disconnect()

        try:
            context = ssl._create_unverified_context()
            self.si = SmartConnect(host=self.host, user=self.user, pwd=self.password, port=self.port, sslContext=context)
            self._cache_cpu_counter_id()
            return self.si
        except Exception as e:
            logger.error(f"[{self.name}] Failed to connect: {e}")
            self.si = None
            return None

    def _disconnect(self):
        if self.si:
            try: Disconnect(self.si)
            except Exception: pass
            self.si = None

    def _cache_cpu_counter_id(self):
        try:
            perf_manager = self.si.RetrieveContent().perfManager
            for counter in perf_manager.perfCounter:
                full_name = f"{counter.groupInfo.key}.{counter.nameInfo.key}.{counter.rollupType}"
                if full_name == "cpu.usage.average":
                    self.cpu_counter_id = counter.key
                    break
        except Exception as e:
            logger.error(f"[{self.name}] Error caching CPU counter: {e}")

    def _ping_vm(self, ip):
        if not ip or ip in ["N/A", "Tools Not Running", "No Network Configured", "Tools Offline", "No Network"]:
            return False, "IP unreachable"
        if os.name == 'nt':
            cmd = ["ping", "-n", "1", "-w", "1000", ip]
        else:
            cmd = ["ping", "-c", "1", "-W", "1", ip]
        try:
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            return True, "Ping OK"
        except Exception:
            return False, "Ping failed"

    def _get_raw_cpu(self, vm_obj, perf_manager):
        if self.cpu_counter_id is None or perf_manager is None: return None
        try:
            metric_id = vim.PerformanceManager.MetricId(counterId=self.cpu_counter_id, instance="")
            query = vim.PerformanceManager.QuerySpec(maxSample=1, entity=vm_obj, metricId=[metric_id], intervalId=20)
            result = perf_manager.QueryPerf(querySpec=[query])
            if result and result[0].value:
                return result[0].value[0].value[0]
            return None
        except Exception:
            return None

    def _process_vm(self, vm_data):
        vm_obj = vm_data['vm_obj']
        name = vm_data['name']
        ip = vm_data['ip']
        perf_mgr = vm_data['perf_mgr']
        
        vm_alerts = []
        powered_on = (vm_obj.runtime.powerState == vim.VirtualMachinePowerState.poweredOn)
        
        ping_ok, ping_msg = self._ping_vm(ip)
        raw_cpu = self._get_raw_cpu(vm_obj, perf_mgr) if powered_on else None
        cpu_raw, cpu_percent = _normalize_cpu(raw_cpu)

        if not powered_on:
            vm_alerts.append(f"{name}: Powered Off")
            final_status = f"Powered Off, CPU usage unknown"
        else:
            pm = (ping_msg or "").lower()
            
            if ip in ["Tools Offline", "No Network"]:
                vm_alerts.append(f"{name}: {ip}")
                final_status = f"{ip}, Normal CPU usage: {cpu_percent}%"
            elif pm == "ip unreachable" or ip == "N/A":
                vm_alerts.append(f"{name}: IP unreachable")
                final_status = f"IP unreachable, Normal CPU usage: {cpu_percent}%"
            elif pm == "ping failed" or not ping_ok:
                vm_alerts.append(f"{name}: Ping failed")
                final_status = f"Ping failed, Normal CPU usage: {cpu_percent}%"
            else:
                final_status = f"Online, Normal CPU usage: {cpu_percent}%"

        if cpu_percent > CPU_HIGH_THRESHOLD:
            vm_alerts.append(f"{name}: High CPU usage {cpu_percent}%")
            final_status = final_status.replace("Normal", "High")
        elif cpu_percent > CPU_MID_THRESHOLD:
            final_status = final_status.replace("Normal", "Moderate")

        for a in vm_data.get('alerts', []):
            if a: vm_alerts.append(a)

        return {
            'name': name,
            'ip': ip,
            'cpu': vm_data['cpu'],
            'ram': vm_data['ram'],
            'ram_usage_gb': vm_data.get('ram_usage_gb'),           # Add this line
            'ram_usage_percent': vm_data.get('ram_usage_percent'), # Add this line
            'disk': vm_data['disk'],
            'disk_usage_percent': vm_data.get('disk_usage_percent'),
            'guest_free_gb': vm_data.get('guest_free_gb'),
            'guest_total_gb': vm_data.get('guest_total_gb'),
            'tools_running': vm_data.get('tools_running'),
            'status': final_status,
            'alerts': _dedupe_preserve_order(vm_alerts),
            'cpu_usage_raw': cpu_raw,
            'cpu_usage_percent': cpu_percent
        }

    def fetch_all_metrics(self):
        si = self._get_connection()
        if not si:
            return {
                'name': self.name,
                'error': True,
                'vms': [],
                'datastores': [],
                'alerts': [f"Critical: Connection to host {self.host} failed."]
            }

        try:
            content = si.RetrieveContent()
            perf_mgr = content.perfManager
            raw_alerts = []

            # 1. Fetch & Process VMs
            container_vms = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
            vm_prep_list = []
            for vm in container_vms.view:
                raw_ip = vm.summary.guest.ipAddress
                tools_status_running = str(vm.guest.toolsRunningStatus)
                tools_status_general = str(vm.guest.toolsStatus)
                
                tools_running = (
                    tools_status_running == 'guestToolsRunning' or 
                    tools_status_general in ['toolsOk', 'toolsOld'] or 
                    raw_ip is not None
                )

                disk_usage_percent = guest_free_gb = guest_total_gb = None
                
                if tools_running and vm.guest.disk:
                    total_capacity = sum([d.capacity for d in vm.guest.disk if d.capacity])
                    total_free = sum([d.freeSpace for d in vm.guest.disk if d.freeSpace])
                    if total_capacity > 0:
                        used_space = total_capacity - total_free
                        disk_usage_percent = round((used_space / total_capacity) * 100, 2)
                        guest_free_gb = round(total_free / (1024 ** 3), 1)
                        guest_total_gb = round(total_capacity / (1024 ** 3), 1)

                if tools_running and raw_ip: ip_display = raw_ip
                elif tools_running: ip_display = "No Network"
                else: ip_display = "Tools Offline"

                # Safely check if storage data exists before reading it
                committed_space = 0
                if vm.summary.storage and vm.summary.storage.committed:
                    committed_space = vm.summary.storage.committed

                # Safely get guest RAM usage and convert from MB to GB
                guest_ram_gb = round((vm.summary.quickStats.guestMemoryUsage or 0) / 1024, 2)
                total_ram_gb = round((vm.summary.config.memorySizeMB or 0) / 1024, 2)
                
                # Calculate percentage
                ram_usage_percent = 0
                if total_ram_gb > 0:
                    ram_usage_percent = round((guest_ram_gb / total_ram_gb) * 100, 2)

                vm_prep_list.append({
                    'name': vm.summary.config.name,
                    'ip': ip_display,
                    'cpu': vm.summary.config.numCpu,
                    'ram': total_ram_gb,
                    'ram_usage_gb': guest_ram_gb,              # NEW
                    'ram_usage_percent': ram_usage_percent,    # NEW
                    'disk': round(committed_space / (1024 ** 3), 2),
                    'disk_usage_percent': disk_usage_percent,
                    'guest_free_gb': guest_free_gb,
                    'guest_total_gb': guest_total_gb,
                    'tools_running': tools_running,
                    'vm_obj': vm,
                    'perf_mgr': perf_mgr,
                    'alerts': []
                })
            container_vms.Destroy()

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                vms_processed = list(executor.map(self._process_vm, vm_prep_list))

            for vm in vms_processed:
                raw_alerts.extend(vm['alerts'])

            # 2. Fetch & Process Datastores
            container_ds = content.viewManager.CreateContainerView(content.rootFolder, [vim.Datastore], True)
            datastores_processed = []
            for ds in container_ds.view:
                free_gb = ds.summary.freeSpace / (1024 ** 3)
                total_gb = ds.summary.capacity / (1024 ** 3)
                used_gb = total_gb - free_gb
                
                usage_percent = (used_gb / total_gb) * 100 if total_gb > 0 else 0
                free_percent = (free_gb / total_gb) * 100 if total_gb > 0 else 0

                if free_percent <= CRITICAL_THRESHOLD: status = "CRITICAL"
                elif free_percent <= WARNING_THRESHOLD: status = "WARNING"
                else: status = "OK"

                datastores_processed.append({
                    'name': ds.name,
                    'type': ds.summary.type,
                    'free': round(free_gb, 2),
                    'used': round(used_gb, 2),
                    'total': round(total_gb, 2),
                    'used_percent': round(usage_percent, 2),
                    'free_percent': round(free_percent, 2),
                    'status': status
                })

                if status in ["WARNING", "CRITICAL"]:
                    raw_alerts.append(f"Datastore '{ds.name}' status: {status} ({round(free_percent, 2)}% free)")
                    if status == "CRITICAL":
                        external_alert(f"Datastore '{ds.name}' is CRITICAL with only {round(free_percent, 2)}% free space!")
            container_ds.Destroy()

            return {
                'name': self.name,
                'error': False,
                'vms': vms_processed,
                'datastores': datastores_processed,
                'alerts': _dedupe_preserve_order(raw_alerts)
            }

        except Exception as e:
            logger.error(f"[{self.name}] Error in background metric update: {e}")
            return {
                'name': self.name,
                'error': True,
                'vms': [],
                'datastores': [],
                'alerts': [f"Critical: Error processing host {self.host}: {e}"]
            }

# -------------------------
# Background Multi-Host Loop
# -------------------------
def start_background_loop():
    """Loops through all servers in servers.local.json and updates the global cache."""
    def loop():
        global GLOBAL_CACHE
        active_monitors = {}
        
        while True:
            servers = load_servers()
            master_payload = {}
            current_ids = []
            
            # Create connections for any new servers added to the JSON
            for s in servers:
                sid = s['id']
                current_ids.append(sid)
                if sid not in active_monitors:
                    logger.info(f"Adding new server to monitoring: {s['name']}")
                    active_monitors[sid] = ESXiMonitor(
                        server_id=sid, name=s['name'], host=s['host'], 
                        user=s['user'], password=s['pass'], port=PORT
                    )
                    
            # Clean up connections for servers removed from the JSON
            for sid in list(active_monitors.keys()):
                if sid not in current_ids:
                    logger.info(f"Removing server from monitoring: {active_monitors[sid].name}")
                    active_monitors[sid]._disconnect()
                    del active_monitors[sid]

            # Fetch data for all active servers
            for sid, monitor in active_monitors.items():
                master_payload[sid] = monitor.fetch_all_metrics()

            # Thread-safe update of the master API payload
            with CACHE_LOCK:
                GLOBAL_CACHE = master_payload

            time.sleep(POLL_INTERVAL_SECONDS)

    # Start the daemon thread
    threading.Thread(target=loop, daemon=True).start()

# -------------------------
# API Endpoints
# -------------------------
@app.route('/api/latest', methods=['GET'])
@swag_from({
    'responses': {
        200: {
            'description': 'Returns multi-host VM and datastore health info instantly from cache.',
            'schema': {
                'type': 'object',
                'description': 'A dictionary where keys are server IDs, and values are the server metrics.'
            }
        }
    }
})
def api_latest():
    """
    Returns the most recent multi-host metrics instantly from the background cache.
    Eliminates ESXi connection overhead on page reloads.
    """
    logger.info('/api/latest called - serving from multi-host cache')
    with CACHE_LOCK:
        return jsonify(GLOBAL_CACHE)


if __name__ == '__main__':
    # Only start the background loop once, avoiding Flask hot-reload double-threading
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        start_background_loop()
        
    app.run(host='0.0.0.0', port=5000, debug=True)