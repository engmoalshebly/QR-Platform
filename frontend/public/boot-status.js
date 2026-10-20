// Independent of the application bundle: a stalled download must remain visible.
(() => {
  const showRecovery = () => {
    const screen = document.getElementById('app-boot-status')
    if (!screen) return
    document.getElementById('app-boot-message').textContent = 'تأخر تحميل الصفحة. تحقق من الاتصال ثم أعد المحاولة.'
    document.getElementById('app-boot-retry').hidden = false
  }
  document.addEventListener('click', event => {
    if (event.target instanceof Element && event.target.id === 'app-boot-retry') window.location.reload()
  })
  window.setTimeout(showRecovery, 15000)
})()
