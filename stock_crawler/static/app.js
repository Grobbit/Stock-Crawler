(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const form = $('#research-form');
  const tickerInput = $('#ticker');
  const formError = $('#form-error');
  const generateButton = $('#generate-button');
  const sampleButtons = [...document.querySelectorAll('.sample-trigger')];
  const preview = $('#preview-state');
  const progress = $('#progress-state');
  const result = $('#result-state');
  const progressBar = $('#progress-bar');
  const progressTrack = $('.progress-track');
  let busy = false;

  function showState(state) {
    preview.hidden = state !== 'preview';
    progress.hidden = state !== 'progress';
    result.hidden = state !== 'result';
  }

  function setBusy(value) {
    busy = value;
    generateButton.disabled = value;
    tickerInput.disabled = value;
    sampleButtons.forEach((button) => { button.disabled = value; });
    document.querySelectorAll('.ticker-chip').forEach((button) => { button.disabled = value; });
  }

  function showError(message) {
    formError.textContent = message;
    formError.hidden = false;
    tickerInput.setAttribute('aria-invalid', 'true');
  }

  function clearError() {
    formError.textContent = '';
    formError.hidden = true;
    tickerInput.removeAttribute('aria-invalid');
  }

  function updateProgress(value, stage) {
    const amount = Math.max(0, Math.min(100, Number(value) || 0));
    $('#progress-percent').textContent = `${Math.round(amount)}%`;
    $('#progress-stage').textContent = stage || 'Working on your research';
    progressBar.style.width = `${amount}%`;
    progressTrack.setAttribute('aria-valuenow', String(Math.round(amount)));
    const steps = [...document.querySelectorAll('.step')];
    const starts = [0, 35, 65, 78];
    steps.forEach((step, index) => {
      const done = index < starts.length - 1 ? amount >= starts[index + 1] : amount >= 100;
      step.classList.toggle('done', done);
      step.classList.toggle('current', !done && amount >= starts[index]);
    });
  }

  function formatPrice(value, currency) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'Not available';
    return `${currency} ${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function showResult(data) {
    $('#result-ticker').textContent = data.ticker;
    $('#result-company').textContent = data.company;
    $('#result-verdict').textContent = data.verdict;
    $('#result-target').textContent = formatPrice(data.target, data.currency);
    $('#demo-banner').hidden = !data.demo;
    const change = data.expected_return === null || data.expected_return === undefined
      ? 'Target withheld until evidence requirements are met.'
      : `Implied price change: ${data.expected_return >= 0 ? '+' : ''}${(data.expected_return * 100).toFixed(1)}% by ${data.target_date}.`;
    $('#result-context').textContent = `${data.pages}-page PDF · ${Math.round(data.coverage * 100)}% factor coverage · Last close ${formatPrice(data.last_close, data.currency)} on ${data.price_date}. ${change}`;
    $('#open-pdf').href = data.pdf_url;
    $('#download-pdf').href = `${data.pdf_url}?download=true`;
    const list = $('#warning-list');
    list.replaceChildren();
    (data.warnings || []).forEach((warning) => {
      const item = document.createElement('li');
      item.textContent = warning;
      list.appendChild(item);
    });
    if (!list.children.length) {
      const item = document.createElement('li');
      item.textContent = 'Data may be delayed or revised; forecasts are illustrative.';
      list.appendChild(item);
    }
    $('#data-notes').open = false;
    showState('result');
  }

  const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  async function apiJson(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The request could not be completed. Please try again.');
    }
    return payload;
  }

  async function runReport(ticker, demo) {
    if (busy) return;
    clearError();
    if (!/^[A-Z0-9^][A-Z0-9.\-=^]{0,24}$/.test(ticker)) {
      showError('Enter a Yahoo Finance ticker, such as AAPL, BRK-B or VOD.L.');
      tickerInput.focus();
      return;
    }
    setBusy(true);
    showState('progress');
    updateProgress(0, 'Waiting for a research slot');
    $('#progress-subtitle').textContent = demo ? 'Building a report from fictional sample data.' : `Researching ${ticker} across available sources.`;
    if (window.matchMedia('(max-width: 650px)').matches) {
      $('#output-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    try {
      const job = await apiJson('/api/reports', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, demo }),
      });
      let transientFailures = 0;
      while (true) {
        await delay(1100);
        let state;
        try {
          state = await apiJson(job.status_url);
          transientFailures = 0;
        } catch (error) {
          if (++transientFailures < 4) continue;
          throw error;
        }
        updateProgress(state.progress, state.stage);
        if (state.status === 'complete') {
          showResult(state.result);
          break;
        }
        if (state.status === 'failed') throw new Error(state.error || 'The report could not be generated.');
      }
    } catch (error) {
      showState('preview');
      showError(error.message || 'Could not reach the research service. Please try again.');
      setBusy(false);
      tickerInput.focus();
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const ticker = tickerInput.value.trim().toUpperCase();
    tickerInput.value = ticker;
    runReport(ticker, false);
  });
  tickerInput.addEventListener('input', clearError);
  document.querySelectorAll('.ticker-chip').forEach((button) => {
    button.addEventListener('click', () => {
      tickerInput.value = button.dataset.ticker;
      clearError();
      tickerInput.focus();
    });
  });
  sampleButtons.forEach((button) => button.addEventListener('click', () => runReport('DEMO', true)));
  $('#start-over').addEventListener('click', () => {
    showState('preview');
    tickerInput.value = '';
    clearError();
    tickerInput.focus();
    document.querySelector('#research').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  apiJson('/api/config').then((config) => {
    $('#sec-status').textContent = config.sec_enabled ? 'SEC FILINGS ENABLED' : 'SEC FILINGS OPTIONAL';
    $('#sec-status').title = config.sec_enabled ? 'SEC filing lookup is configured.' : 'Set SEC_USER_AGENT to enable SEC filing lookup.';
  }).catch(() => { /* The page remains usable; report requests will show a useful error. */ });
})();
