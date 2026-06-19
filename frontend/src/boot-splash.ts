// Hide the boot splash as soon as React has painted something into #root.
const obs = new MutationObserver(() => {
  const root = document.getElementById('root')
  if (root && root.childElementCount > 0) {
    const boot = document.getElementById('boot')
    if (boot) {
      boot.classList.add('hide')
      setTimeout(() => boot.remove(), 400)
    }
    obs.disconnect()
  }
})
const rootEl = document.getElementById('root')
if (rootEl) obs.observe(rootEl, { childList: true, subtree: true })
