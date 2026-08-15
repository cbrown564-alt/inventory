const frames = {
  'A-wide': { image: '../evals/fixtures/synthetic-room-eval/images/openai/gpt-image-2/RP-001-A-wide.png', alt: 'Synthetic Kitchen wide view showing pale units, dark worktop, sink, oven, hob and extractor hood', hash: '6dc1764c92b3f8c21acf2ef0d46403aa9e6982b0a5e9499462020c2b5d2ccee0' },
  'B-reverse': { image: '../evals/fixtures/synthetic-room-eval/images/openai/gpt-image-2/RP-001-B-reverse.png', alt: 'Synthetic Kitchen reverse view showing the opposite corner, blind, radiator, door furniture and skirting', hash: '4fa9817d6e858947b36f72a906a04bd3484a663814c547216f8f0e99a3b4bbe1' },
  'C-inventory': { image: '../evals/fixtures/synthetic-room-eval/images/openai/gpt-image-2/RP-001-C-inventory.png', alt: 'Synthetic Kitchen inventory view showing extractor hood, hob, oven, smoke alarm, splashback and sockets', hash: '5fe1d437e6e160a84dfab0625eaa0103dd13958a67d3240d703f76d499044d1d' },
  'D-condition': { image: '../evals/fixtures/synthetic-room-eval/images/openai/gpt-image-2/RP-001-D-condition.png', alt: 'Synthetic Kitchen condition view showing the base unit door, plinth, vinyl floor and skirting', hash: '414e26b83d4a45cd198ddb061334e734646b54f0a4407317be1761644cb04095' }
};
const claims = {
  kitchen: [
    { id: 'KITCHEN-01', title: 'Kitchen units', status: 'Agreed', statusClass: 'badge-reviewed', frames: ['A-wide', 'B-reverse', 'C-inventory', 'D-condition'], description: 'Pale wood-effect fronts; one lower door has the separately recorded small chip.', review: 'Second review agreed · Conor Brown' },
    { id: 'KITCHEN-02', title: 'Base unit door', status: 'Agreed · minor chip', statusClass: 'badge-noted', frames: ['D-condition'], description: 'Small localised chip on the lower edge; the remainder appears intact in this view.', defect: 'Small chip · lower edge of the corner base-unit door · minor', review: 'Second review agreed · Conor Brown' },
    { id: 'KITCHEN-03', title: 'Wood grain is not mould', status: 'Supported', statusClass: 'badge-reviewed', frames: ['A-wide', 'C-inventory', 'D-condition'], description: 'Wood grain is not mould.', review: 'Negative control · second review agreed · Conor Brown' },
    { id: 'KITCHEN-04', title: 'Dark worktop', status: 'Pending second review', statusClass: 'badge-pending', frames: ['A-wide', 'B-reverse', 'C-inventory', 'D-condition'], description: 'Dark worktop visible across the accepted packet. No condition label is recorded.', review: 'Second review pending' }
  ]
};
let activeRoom = 'kitchen';
let activeClaim = 0;
let activeFrame = 0;
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function renderClaims() {
  const list = $('#claim-buttons');
  list.replaceChildren(...claims[activeRoom].map((claim, index) => {
    const button = document.createElement('button');
    button.type = 'button'; button.className = `claim-button${index === activeClaim ? ' is-active' : ''}`;
    button.setAttribute('aria-pressed', index === activeClaim); button.dataset.index = index;
    button.innerHTML = `<span class="claim-number">${String(index + 1).padStart(2, '0')}</span><span><strong>${claim.title}</strong><small>${claim.id} · ${claim.frames.length} cited frame${claim.frames.length === 1 ? '' : 's'}</small></span><span class="claim-state ${claim.statusClass}">${claim.status}</span>`;
    button.addEventListener('click', () => { activeClaim = index; activeFrame = 0; renderClaims(); renderEvidence(); });
    return button;
  }));
}
function renderEvidence() {
  const claim = claims[activeRoom][activeClaim];
  $('#room-title').textContent = 'Kitchen';
  $('#claim-title').textContent = claim.title; $('#claim-status').textContent = claim.status; $('#claim-status').className = `badge ${claim.statusClass}`;
  const frameId = claim.frames[activeFrame]; const frame = frames[frameId];
  const image = $('#evidence-image'); image.src = frame.image; image.alt = frame.alt;
  $('#photo-id').textContent = frameId; $('#photo-context').textContent = `Kitchen · ${frameId} · Pass A accepted`; $('#claim-description').textContent = claim.description;
  $('#evidence-ref').textContent = claim.frames.join(' · '); $('#review-ref').textContent = claim.review; $('#hash-ref').textContent = `${frame.hash.slice(0, 8)}…${frame.hash.slice(-7)}`; $('#hash-ref').title = frame.hash;
  const note = $('#defect-note'); note.replaceChildren(); if (claim.defect) { const p = document.createElement('p'); p.className = 'finding-note'; p.innerHTML = `<span>Recorded defect</span>${claim.defect}`; note.appendChild(p); }
  const frameList = $('#frame-buttons'); frameList.replaceChildren(...claim.frames.map((id, index) => { const button = document.createElement('button'); button.type = 'button'; button.className = `frame-button${index === activeFrame ? ' is-active' : ''}`; button.setAttribute('aria-label', `Show ${id} frame`); button.innerHTML = `<img src="${frames[id].image}" alt=""><span>${id}</span>`; button.addEventListener('click', () => { activeFrame = index; renderEvidence(); }); return button; }));
}
function showView(view) {
  $$('[data-panel]').forEach(panel => { panel.hidden = panel.dataset.panel !== view; });
  $$('.nav-button').forEach(button => button.classList.toggle('is-active', button.dataset.view === view));
  if (view === 'review') $('#page-title').focus({ preventScroll: true }); else $('#report-title').focus({ preventScroll: true });
}
$$('.room-tab').forEach(tab => tab.addEventListener('click', () => { activeRoom = tab.dataset.room; activeClaim = 0; activeFrame = 0; $$('.room-tab').forEach(item => { const selected = item === tab; item.classList.toggle('is-active', selected); item.setAttribute('aria-selected', selected); }); renderClaims(); renderEvidence(); }));
$$('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
$('#report-button').addEventListener('click', () => showView('report'));
$('#next-button').addEventListener('click', () => { activeClaim = (activeClaim + 1) % claims[activeRoom].length; activeFrame = 0; renderClaims(); renderEvidence(); });
$('#claim-buttons').addEventListener('keydown', (event) => { if (!['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return; event.preventDefault(); const buttons = $$('#claim-buttons button'); if (event.key === 'Enter') buttons[activeClaim].click(); else { activeClaim = (activeClaim + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length; renderClaims(); renderEvidence(); buttons[activeClaim].focus(); } });
renderClaims(); renderEvidence();
