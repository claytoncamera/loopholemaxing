// Public portfolio figures come from the same ledger as the research page.
// A failed refresh must never turn a previous number into a current claim.
export function ledgerSummary(data, now = Date.now()) {
  const g = data?.global;
  const timestamp = typeof data?.generated_at === 'string' ? Date.parse(data.generated_at) : NaN;
  if (!g || !Number.isSafeInteger(g.n) || g.n < 1 || g.display_ready !== true ||
      !Number.isFinite(g.hit_rate) || g.hit_rate < 0 || g.hit_rate > 1 ||
      !Number.isFinite(g.vs_majority_pp) || Math.abs(g.vs_majority_pp) > 100 ||
      !Number.isFinite(timestamp) || timestamp > now + 300000) {
    throw new Error('Incomplete ledger snapshot');
  }
  const gap = g.vs_majority_pp;
  const baseline = Math.abs(gap) < 0.05 ? 'level with the majority baseline' :
    `${Math.abs(gap).toFixed(1)} percentage points ${gap > 0 ? 'ahead of' : 'behind'} the majority baseline`;
  const age = now - timestamp;
  const dated = new Date(timestamp).toISOString().replace('T', ' ').replace('.000Z', ' UTC');
  return {
    count: g.n.toLocaleString('en-US'),
    record: `${(g.hit_rate * 100).toFixed(1)}% global hit rate; ${baseline}. This is research, not evidence of a tradable edge.`,
    time: `Ledger snapshot: ${dated}${age > 86400000 ? ' — over 24 hours old; refresh delayed.' : '.'}`,
  };
}

export async function refreshLedger(doc, fetcher, now = Date.now()) {
  let result;
  try {
    const response = await fetcher('/btc-brain/ledger/public/accuracy.json', {
      cache: 'no-store', signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error('Ledger unavailable');
    result = ledgerSummary(await response.json(), now);
  } catch (_) {
    result = {
      count: '—',
      record: 'Current ledger unavailable here. Open BTC Brain for its scorecard and source status.',
      time: 'No current figure shown.',
    };
  }
  doc.querySelectorAll('[data-btc-resolved]').forEach(el => { el.textContent = result.count; });
  doc.getElementById('btc-record-summary').textContent = result.record;
  doc.getElementById('btc-record-time').textContent = result.time;
}

if (typeof document !== 'undefined') refreshLedger(document, fetch);
