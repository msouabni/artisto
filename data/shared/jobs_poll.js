/**
 * jobs_poll.js — Helper pour suivre un job asynchrone via polling.
 *
 * Usage :
 *   const poller = JobsPoller.start(jobId, {
 *     apiBase: '',            // préfixe API (ex. 'http://localhost:8000')
 *     pollIntervalMs: 2000,   // intervalle entre polls (défaut 2s)
 *     maxWaitMs: 120000,      // timeout total (défaut 2 min)
 *     onProgress: (job) => {},           // appelé à chaque poll running
 *     onDone: (job) => {},               // appelé quand awaiting_validation ou completed/applied
 *     onError: (msg, job) => {},         // appelé sur échec ou timeout
 *   });
 *   poller.stop(); // annulation manuelle
 *
 * Terminaux (onDone) : 'awaiting_validation', 'completed', 'applied', 'rejected'
 * Terminaux (onError) : 'failed', 'cancelled', timeout, erreur réseau
 */
(function (global) {
  'use strict';

  const TERMINAL_DONE = new Set(['awaiting_validation', 'completed', 'applied', 'rejected']);
  const TERMINAL_ERROR = new Set(['failed', 'cancelled']);

  /**
   * @param {string} jobId
   * @param {Object} opts
   */
  function startPoller(jobId, opts) {
    const apiBase = opts.apiBase || '';
    const pollIntervalMs = opts.pollIntervalMs || 2000;
    const maxWaitMs = opts.maxWaitMs || 120000;
    const onProgress = opts.onProgress || function () {};
    const onDone = opts.onDone || function () {};
    const onError = opts.onError || function (msg) { console.error('[JobsPoller]', msg); };

    let stopped = false;
    let timeoutId = null;
    const startedAt = Date.now();

    function poll() {
      if (stopped) return;
      if (Date.now() - startedAt > maxWaitMs) {
        onError('Timeout : le job ' + jobId + ' n\'a pas terminé dans les ' + (maxWaitMs / 1000) + 's impartis.', null);
        return;
      }
      fetch(apiBase + '/api/jobs?type%5B%5D=&status%5B%5D=&page=1&page_size=1&id=' + encodeURIComponent(jobId))
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        })
        .then(function (data) {
          // On passe par /api/jobs/{id} directement — essai d'abord via list puis fallback
          return data;
        })
        .catch(function () { return null; })
        .then(function (_) {
          // Fetch direct le job par id
          return fetch(apiBase + '/api/jobs/' + encodeURIComponent(jobId)).catch(function () { return null; });
        })
        .then(function (res) {
          if (!res || !res.ok) {
            // Fallback : chercher dans la liste
            return fetch(apiBase + '/api/jobs?page_size=1&sort=created_at&order=desc')
              .then(function (r) { return r.ok ? r.json() : null; })
              .then(function (data) {
                if (!data) return null;
                return (data.jobs || []).find(function (j) { return j.id === jobId; }) || null;
              });
          }
          // GET /api/jobs/{id} n'existe pas forcément — utiliser list avec filtre
          return null;
        })
        .catch(function () { return null; })
        .then(function (_) {
          // Utilise la route /api/jobs avec entity_id ou batch_ref non fiable — utiliser polling sur list
          _pollViaList();
        });
    }

    function _pollViaList() {
      if (stopped) return;
      // Utilise GET /api/jobs?... pour trouver le job par id
      // On filtre par page_size et sort pour trouver rapidement.
      fetch(apiBase + '/api/jobs?page_size=50&sort=created_at&order=desc')
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        })
        .then(function (data) {
          const jobs = data.jobs || [];
          const job = jobs.find(function (j) { return j.id === jobId; });
          _handleJob(job || null);
        })
        .catch(function (err) {
          onError('Erreur réseau lors du poll : ' + err.message, null);
          // Réessayer après un délai plus long
          if (!stopped) {
            timeoutId = setTimeout(poll, pollIntervalMs * 3);
          }
        });
    }

    function _handleJob(job) {
      if (stopped) return;
      if (!job) {
        // Job non trouvé (peut être dans une page plus ancienne) — réessayer
        timeoutId = setTimeout(poll, pollIntervalMs);
        return;
      }
      const status = job.status;
      if (TERMINAL_DONE.has(status)) {
        onDone(job);
        return;
      }
      if (TERMINAL_ERROR.has(status)) {
        onError(
          'Job ' + jobId + ' terminé en erreur (status=' + status + ') : ' + (job.error_message || ''),
          job
        );
        return;
      }
      // Toujours en cours (pending, running)
      onProgress(job);
      timeoutId = setTimeout(poll, pollIntervalMs);
    }

    // Override _pollViaList dans poll pour démarrer directement
    function start() {
      timeoutId = setTimeout(_pollViaList, 200); // premier poll rapide
    }

    start();

    return {
      stop: function () {
        stopped = true;
        if (timeoutId) { clearTimeout(timeoutId); timeoutId = null; }
      }
    };
  }

  /**
   * Raccourci : enqueue un job via POST /api/jobs/enqueue puis démarre le polling.
   *
   * @param {Object} enqueueBody  — corps JSON pour /api/jobs/enqueue
   * @param {Object} opts         — même options que startPoller + apiBase
   * @returns {Promise<Object>}   — résout avec le poller (ou rejet si enqueue échoue)
   */
  function enqueueAndPoll(enqueueBody, opts) {
    const apiBase = opts.apiBase || '';
    return fetch(apiBase + '/api/jobs/enqueue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(enqueueBody),
    })
      .then(function (res) {
        if (!res.ok) {
          return res.json().then(function (data) {
            throw new Error((data && data.detail) ? String(data.detail) : 'Erreur ' + res.status);
          });
        }
        return res.json();
      })
      .then(function (data) {
        const jobId = data.id || data.job_id;
        if (!jobId) throw new Error('Réponse enqueue sans job_id');
        return startPoller(jobId, opts);
      });
  }

  /**
   * Raccourci : appelle un endpoint /api/ai/* et démarre le polling si la réponse est HTTP 202.
   * Si la réponse est 200 (mode sync ou endpoint admin), appelle onDone directement.
   *
   * @param {string} url          — ex. '/api/ai/enrich-term'
   * @param {Object} body         — corps JSON
   * @param {Object} opts         — options poller + apiBase
   * @returns {Promise<Object|null>}
   */
  function callAndPoll(url, body, opts) {
    const apiBase = opts.apiBase || '';
    return fetch(apiBase + url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (res) {
        if (!res.ok) {
          return res.json().then(function (data) {
            throw new Error((data && data.detail) ? String(data.detail) : 'Erreur ' + res.status);
          });
        }
        return res.json().then(function (data) {
          return { status: res.status, data: data };
        });
      })
      .then(function (result) {
        if (result.status === 202) {
          // Mode async : démarrer le polling
          const jobId = result.data.job_id || result.data.id;
          if (!jobId) throw new Error('Réponse 202 sans job_id');
          return startPoller(jobId, opts);
        }
        // Mode sync : résultat immédiat — simuler onDone avec un objet job factice
        if (opts.onDone) {
          opts.onDone({ status: 'completed', result: JSON.stringify(result.data), _direct: true, _data: result.data });
        }
        return null;
      });
  }

  const JobsPoller = {
    start: startPoller,
    enqueueAndPoll: enqueueAndPoll,
    callAndPoll: callAndPoll,
  };

  global.JobsPoller = JobsPoller;
})(window);
