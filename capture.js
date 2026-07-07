/* Loopholemaxing email capture
 *
 * Posts signups to the LoopholeMaxing HUB CRM via its public intake
 * endpoint (CORS-cleared for this origin). Signups land as leads with
 * business_name prefixed "[LIST] <list name>" so they're filterable
 * from real agency leads inside the HUB.
 *
 * Usage:  await loopholeCapture('you@x.com', 'ULTRON Pro Waitlist', 'optional note')
 * Throws on network/validation failure — callers show their own fallback.
 */
(function () {
  const INTAKE_URL = 'https://hubapi.loopholemaxing.com/api/v1/leads/intake';

  window.loopholeCapture = async function (email, list, note) {
    email = String(email || '').trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      throw new Error('invalid email');
    }
    const payload = {
      business_name: '[LIST] ' + list,
      contact_name: email.split('@')[0],
      email: email,
      phone: 'n/a',
      notes: (note ? note + ' | ' : '') + 'page: ' + location.pathname
    };
    const res = await fetch(INTAKE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('capture failed: HTTP ' + res.status);
    return res.json();
  };

  /* Wire a simple <form> with one email input to a list.
     opts: { form, input, okEl, list, note }  — okEl shown + form hidden on success.
     On failure the form stays visible and the input border flags red. */
  window.wireCaptureForm = function (opts) {
    const form = typeof opts.form === 'string' ? document.getElementById(opts.form) : opts.form;
    const input = typeof opts.input === 'string' ? document.getElementById(opts.input) : opts.input;
    const okEl = typeof opts.okEl === 'string' ? document.getElementById(opts.okEl) : opts.okEl;
    if (!form || !input) return;
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"], button');
      const prev = btn ? btn.textContent : '';
      if (btn) { btn.disabled = true; btn.textContent = '…'; }
      try {
        await window.loopholeCapture(input.value, opts.list, opts.note);
        form.style.display = 'none';
        if (okEl) okEl.style.display = 'block';
      } catch (err) {
        input.style.borderColor = '#f85149';
        if (btn) { btn.disabled = false; btn.textContent = prev; }
      }
    });
  };
})();
