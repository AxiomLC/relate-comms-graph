# Sets user-scope env vars for Ollama on this box.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File tools/set_ollama_env.ps1
$vars = @{
    # Force CPU. The Iris Xe iGPU shares the same LPDDR5 bus as the CPU, and decode is
    # bandwidth-bound, so the iGPU cannot help. Verified: `ollama ps` reports 100% CPU.
    OLLAMA_VULKAN            = '0'

    OLLAMA_CONTEXT_LENGTH    = '8192'
    OLLAMA_FLASH_ATTENTION   = '1'
    OLLAMA_KV_CACHE_TYPE     = 'q8_0'

    # How long a MODEL stays in RAM after your last request. This is NOT the service
    # lifetime - closing the Ollama service frees everything regardless.
    # 5m = models evict themselves when idle, so RAM returns without a restart.
    # (Was -1 = "never unload", which is only right for a long unattended batch run.)
    OLLAMA_KEEP_ALIVE        = '5m'

    # Parallel requests multiply KV memory. 1 is correct for a 16 GB box.
    OLLAMA_NUM_PARALLEL      = '1'

    # Only one model resident at a time, so a big model can't sit alongside another.
    # Combined with KEEP_ALIVE=5m this means: use it, stop, it goes away.
    OLLAMA_MAX_LOADED_MODELS = '1'

    # The product promise: nothing leaves the machine.
    OLLAMA_NO_CLOUD          = '1'
}

foreach ($k in $vars.Keys) {
    [Environment]::SetEnvironmentVariable($k, $vars[$k], 'User')
    Write-Output ("{0}={1}" -f $k, $vars[$k])
}

Write-Output '--- verify ---'
foreach ($k in $vars.Keys) {
    Write-Output ("{0}={1}" -f $k, [Environment]::GetEnvironmentVariable($k, 'User'))
}
