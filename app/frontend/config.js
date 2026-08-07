// Keep browser requests on the APP VM origin. The APP VM's Nginx service
// forwards /api requests to the separate API VM, so session cookies never
// become third-party/cross-site cookies merely because the VMs use different
// ZeroTier IP addresses.
window.BACKEND_BASE_URL = window.location.origin;
