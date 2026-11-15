<template>
  <div class="p-6 bg-gray-50 min-h-screen transition-colors duration-300">

    <!-- Header & Server Selector -->
    <div class="mb-8 py-4 px-6 bg-slate-800 text-white rounded-xl shadow-md flex flex-col md:flex-row items-center justify-between gap-4">
      <h1 class="text-3xl font-extrabold flex items-center gap-4 tracking-wide m-0">
        <i class="pi pi-server text-3xl text-blue-400"></i>
        VM & Datastore Dashboard
      </h1>
      
      <!-- NEW: Server Selector -->
      <div class="flex items-center gap-3">
        <label for="serverSelect" class="font-medium text-slate-300 whitespace-nowrap">
          <i class="pi pi-desktop mr-1"></i> Host:
        </label>
        <select 
          id="serverSelect" 
          v-model="selectedServerId" 
          class="p-2 bg-slate-700 text-white border border-slate-600 rounded cursor-pointer outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 transition-colors"
        >
          <option v-for="server in serverOptions" :key="server.value" :value="server.value">
            {{ server.label }}
          </option>
        </select>
      </div>
    </div>

    <!-- Critical Connection Error -->
    <div v-if="isError" class="mb-6 p-4 bg-red-100 border-l-4 border-red-500 text-red-800 rounded-lg shadow-sm flex items-start gap-3">
      <i class="pi pi-exclamation-triangle text-2xl mt-0.5"></i>
      <div>
        <h3 class="font-bold text-lg mb-1">Host Offline or Unreachable</h3>
        <p>The monitoring script could not connect to this ESXi host. Check your network or credentials.</p>
      </div>
    </div>

    <!-- Alerts Section (Now reactive to the selected server) -->
    <div v-if="alerts.length" class="mb-6">
      <h2 class="text-2xl font-bold mb-4 py-2 px-4 bg-rose-100 text-rose-900 rounded-lg shadow-sm border-l-4 border-rose-500 flex items-center gap-2">
        <i class="pi pi-bell text-xl"></i>
        Alerts
      </h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div v-for="(alert, index) in alerts" :key="index" class="p-3 rounded-lg flex items-center gap-3 font-medium"
             :class="alertClass(alert)">
          <i :class="alertIcon(alert) + ' text-lg'"></i>
          <span>{{ alert }}</span>
        </div>
      </div>
    </div>

    <!-- VMs Table (Hides if connection error) -->
    <div class="mb-8" v-if="!isError">
      <h2 class="text-2xl font-bold mb-4 py-2 px-4 bg-blue-100 text-blue-900 rounded-lg shadow-sm border-l-4 border-blue-500 flex items-center gap-2">
        <i class="pi pi-desktop text-xl"></i>
        Machines Virtuelles
      </h2>
      <Card>
        <template #content>
        <DataTable :value="vms" responsiveLayout="scroll" stripedRows class="shadow-sm rounded-lg">
          <Column field="name" header="Nom" :style="{ maxWidth: '150px' }">
            <template #body="slotProps">
              <span class="truncate font-semibold">{{ slotProps.data.name }}</span>
            </template>
          </Column>
          <Column field="ip" header="IP Address">
            <template #body="slotProps">
              <!-- Check if the IP is an actual IP or one of our fallback statuses -->
              <span v-if="['Tools Offline', 'No Network', 'N/A'].includes(slotProps.data.ip)" 
                    class="text-sm text-gray-500 italic">
                {{ slotProps.data.ip }}
              </span>
              
              <!-- Render normal IP addresses with default styling -->
              <span v-else class="font-medium text-gray-800">
                {{ slotProps.data.ip }}
              </span>
            </template>
          </Column>
          <Column field="cpu" header="vCPU" />
          <Column header="Usage RAM (GB)">
            <template #body="slotProps">
              <div v-if="slotProps.data.tools_running" class="relative w-full">
                <!-- Reusing your cpuBarColor function for the color thresholds -->
                <ProgressBar :value="slotProps.data.ram_usage_percent"
                             :color="cpuBarColor(slotProps.data.ram_usage_percent)"
                             :showValue="false" />
                
                <span class="absolute inset-0 flex items-center justify-center font-semibold text-gray-800 pointer-events-none text-sm z-10">
                  {{ slotProps.data.ram_usage_gb }} / {{ slotProps.data.ram }} ({{ slotProps.data.ram_usage_percent }}%)
                </span>
              </div>
              
              <div v-else class="text-sm text-gray-500 italic text-center w-full">
                Tools Offline
              </div>
            </template>
          </Column>
          <Column header="Guest Disk Usage (GB)">
            <template #body="slotProps">
              <div v-if="slotProps.data.tools_running && slotProps.data.disk_usage_percent !== null" class="relative w-full">
                <ProgressBar :value="slotProps.data.disk_usage_percent"
                             :color="diskBarColor(slotProps.data.disk_usage_percent)"
                             :showValue="false" />
                             
                <!-- Updated label to show Free / Total alongside the Percentage -->
                <span class="absolute inset-0 flex items-center justify-center font-semibold text-gray-800 pointer-events-none text-sm z-10">
                  {{ slotProps.data.guest_free_gb }} / {{ slotProps.data.guest_total_gb }} ({{ slotProps.data.disk_usage_percent }}%)
                </span>
              </div>
              
              <div v-else class="text-sm text-gray-500 italic text-center w-full">
                {{ slotProps.data.tools_running ? 'No Disk Data' : 'Tools Offline' }}
              </div>
            </template>
          </Column>
          <Column header="Usage CPU">
            <template #body="slotProps">
              <div class="relative w-full">
                <!-- Turn off PrimeVue's built-in label -->
                <ProgressBar :value="slotProps.data.cpu_usage_percent"
                             :color="cpuBarColor(slotProps.data.cpu_usage_percent)"
                             :showValue="false" />
                
                <!-- Overlay your own perfectly centered text using Tailwind -->
                <span class="absolute inset-0 flex items-center justify-center font-semibold text-gray-800 pointer-events-none text-sm z-10">
                  {{ slotProps.data.cpu_usage_percent }}%
                </span>
              </div>
            </template>
          </Column>
          <Column header="Status">
            <template #body="slotProps">
              <div class="flex items-center gap-2">
                <i :class="vmStatusIcon(slotProps.data.status)"></i>
                <Badge :value="slotProps.data.status" :severity="statusSeverity(slotProps.data.status)" />
              </div>
            </template>
          </Column>
        </DataTable>
        </template>
      </Card>
    </div>

    <!-- Datastores Table (Hides if connection error) -->
    <div v-if="!isError">
      <h2 class="text-2xl font-bold mb-4 py-2 px-4 bg-purple-100 text-purple-900 rounded-lg shadow-sm border-l-4 border-purple-500 flex items-center gap-2">
        <i class="pi pi-database text-xl"></i>
        Datastores
      </h2>
      <Card>
        <template #content>
          <DataTable :value="datastores" responsiveLayout="scroll" stripedRows class="shadow-sm rounded-lg">
            <Column field="name" header="Nom" :style="{ maxWidth: '180px' }">
              <template #body="slotProps">
                <span class="truncate font-semibold">{{ slotProps.data.name }}</span>
              </template>
            </Column>
            <Column field="type" header="Type" />
            <Column header="Libre / Total (GB)">
              <template #body="slotProps">
                <!-- Using the precise math from the backend -->
                <span>{{ slotProps.data.free }} / {{ slotProps.data.total }}</span>
              </template>
            </Column>
            <Column header="Usage">
              <template #body="slotProps">
                <div class="relative w-full">
                  <ProgressBar :value="slotProps.data.used_percent"
                               :color="datastoreBarColor(slotProps.data.used_percent)"
                               :showValue="false" />
                               
                  <span class="absolute inset-0 flex items-center justify-center font-semibold text-gray-800 pointer-events-none text-sm z-10">
                    {{ slotProps.data.used_percent }}%
                  </span>
                </div>
              </template>
            </Column>
            <Column field="status" header="Status">
              <template #body="slotProps">
                <Badge :value="slotProps.data.status" :severity="statusSeverity(slotProps.data.status)" />
              </template>
            </Column>
          </DataTable>
        </template>
      </Card>
    </div>
  </div>
</template>

<script>
import axios from "axios";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:5001").replace(/\/+$/, "");

export default {
  name: "App",
  data() {
    return {
      rawServerData: {},       // Holds the massive nested JSON from the backend
      selectedServerId: null,  // Tracks which server ID is currently chosen in the dropdown
      serverOptions: [],       // Used to build the dropdown options
      refreshInterval: null,
    };
  },
  computed: {
    // These automatically recalculate whenever selectedServerId changes!
    activeServer() {
      if (this.selectedServerId && this.rawServerData[this.selectedServerId]) {
        return this.rawServerData[this.selectedServerId];
      }
      return { vms: [], datastores: [], alerts: [], error: false };
    },
    vms() {
      return this.activeServer.vms || [];
    },
    datastores() {
      return this.activeServer.datastores || [];
    },
    alerts() {
      return this.activeServer.alerts || [];
    },
    isError() {
      return this.activeServer.error === true;
    }
  },
  methods: {
    fetchData() {
      axios.get(`${API_BASE_URL}/api/latest`)
        .then(res => {
          this.rawServerData = res.data;
          
          // Dynamically build the dropdown options based on the backend data
          const options = [];
          for (const [id, serverInfo] of Object.entries(this.rawServerData)) {
            options.push({ label: serverInfo.name, value: id });
          }
          this.serverOptions = options;

          // If the user hasn't selected a server yet, select the first one by default
          if (!this.selectedServerId && options.length > 0) {
            this.selectedServerId = options[0].value;
          }
        })
        .catch(err => console.error("Error fetching monitoring data:", err));
    },
    
    // ==========================================
    // Formatting Methods (Untouched)
    // ==========================================
    statusSeverity(status) {
      if (!status) return "info";
      const s = status.toLowerCase();
      
      if (s.includes("critical") || s.includes("high") || s.includes("powered off")) return "danger";
      if (s.includes("warning") || s.includes("moderate") || s.includes("unreachable") || s.includes("ping failed") || s.includes("offline") || s.includes("no network")) return "warning";
      if (s.includes("ok") || s.includes("normal") || s.includes("online")) return "success";
      
      return "info";
    },
    
    cpuBarColor(value) {
      if (value > 80) return "red";
      if (value > 40) return "orange";
      return "green";
    },
    
    diskBarColor(percent) {
      if (percent < 75) return '#22c55e'; // Green - Healthy
      if (percent < 90) return '#f59e0b'; // Orange - Warning
      return '#ef4444';                   // Red - Critical
    },
    
    datastoreBarColor(value) {
      if (value > 80) return "red";
      if (value > 50) return "orange";
      return "green";
    },
    
    vmStatusIcon(status) {
      const s = status.toLowerCase();
      
      if (s.includes("powered off")) return "pi pi-power-off text-gray-500";
      if (s.includes("ip unreachable") || s.includes("ping failed")) return "pi pi-times-circle text-red-500";
      if (s.includes("tools offline") || s.includes("no network")) return "pi pi-exclamation-circle text-yellow-500";
      if (s.includes("online")) return "pi pi-power-on text-green-500";
      
      return "pi pi-info-circle text-blue-500";
    },
    
    alertClass(alert) {
      const lower = alert.toLowerCase();
      if (lower.includes("critical") || lower.includes("high")) return "bg-red-100 text-red-800";
      if (lower.includes("warning") || lower.includes("moderate") || lower.includes("offline") || lower.includes("no network")) return "bg-orange-100 text-orange-800";
      if (lower.includes("powered off") || lower.includes("unreachable") || lower.includes("ping failed")) return "bg-gray-100 text-gray-800";
      
      return "bg-blue-100 text-blue-800";
    },
    
    alertIcon(alert) {
      const lower = alert.toLowerCase();
      if (lower.includes("critical") || lower.includes("high")) return "pi pi-exclamation-triangle";
      if (lower.includes("warning") || lower.includes("moderate") || lower.includes("offline") || lower.includes("no network")) return "pi pi-exclamation-circle";
      if (lower.includes("powered off") || lower.includes("unreachable") || lower.includes("ping failed")) return "pi pi-times-circle";
      
      return "pi pi-info-circle";
    }
  },
  mounted() {
    this.fetchData();
    this.refreshInterval = setInterval(this.fetchData, 30000); // Refresh every 30 seconds
  },
  beforeUnmount() {
    clearInterval(this.refreshInterval);
  }
};
</script>

<style scoped>
:deep(.p-progressbar) {
  position: relative;
  overflow: hidden;
}

:deep(.p-progressbar-label) {
  position: absolute;
  width: 100%;
  left: 0;
  text-align: center;
  font-weight: 600;
  z-index: 10;
  color: #374151; 
}
.truncate {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>