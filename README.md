# ESXi Multi-Host Monitor

## Server configuration

Server addresses and ESXi credentials belong in a local configuration file, not in Git.
The repository includes a placeholder configuration at `servers.example.json`.

For Docker Compose, create `servers.local.json` from the example if it does not already
exist, then replace the placeholder values with your ESXi hosts and credentials:

```powershell
Copy-Item .\servers.example.json .\servers.local.json
```

Docker Compose mounts this local file read-only into the backend. Start the project with:

```powershell
docker compose up --build
```

The dashboard defaults to `http://localhost:5001` for the backend API. If browsers will
access the dashboard from another machine, copy `.env.example` to `.env` and set
`VITE_API_BASE_URL` to an address reachable from those browsers, then rebuild the frontend.
The local `.env` file is excluded from Git.

When running the backend directly instead, place a configured copy at
`backend/servers.local.json`. Both local configuration paths are excluded from Git.

Do not force-add local configuration files. If credentials or internal host details were
already pushed, rotate the credentials and remove the sensitive data from the repository's
history before making it public; deleting a file in a new commit does not erase older
commits.
