// Safe override for django-webpush webpush.js
var isPushEnabled = false,
    registration,
    subBtn;

window.addEventListener('load', function() {
  subBtn = document.getElementById('webpush-subscribe-button');
  if (!subBtn) {
    // If subscribe button is not present on current page, safely exit without error
    return;
  }

  if (typeof gettext === 'function') {
    subBtn.textContent = gettext('Subscribe to Push Messaging');
  }

  subBtn.addEventListener('click', function() {
    subBtn.disabled = true;
    if (isPushEnabled) {
      return unsubscribe(registration);
    }
    return subscribe(registration);
  });

  if ('serviceWorker' in navigator) {
    const swMeta = document.querySelector('meta[name="service-worker-js"]');
    const serviceWorkerUrl = swMeta ? swMeta.content : '/service-worker.js';
    navigator.serviceWorker.register(serviceWorkerUrl).then(function(reg) {
      registration = reg;
      initialiseState(reg);
    }).catch(function(err) {
      console.warn('Service worker registration failed:', err);
    });
  } else {
    showMessage('Service workers are not supported in your browser.');
  }

  function initialiseState(reg) {
    if (!reg || !reg.showNotification) return;

    if (Notification.permission === 'denied') {
      if (subBtn) subBtn.disabled = false;
      showMessage('Push notifications are blocked by your browser.');
      return;
    }

    if (!('PushManager' in window)) {
      if (subBtn) subBtn.disabled = false;
      showMessage('Push notifications are not available in your browser.');
      return;
    }

    reg.pushManager.getSubscription().then(function(subscription) {
      if (subscription) {
        postSubscribeObj('subscribe', subscription, function(response) {
          if (response && (response.status === 201 || response.status === 200)) {
            if (subBtn) {
              subBtn.textContent = (typeof gettext === 'function') ? gettext('Unsubscribe from Push Messaging') : 'Unsubscribe from Push Messaging';
              subBtn.disabled = false;
            }
            isPushEnabled = true;
            showMessage('Successfully subscribed to push notifications.');
          }
        });
      }
    });
  }
});

function showMessage(message) {
  const messageBoxes = document.querySelectorAll('#webpush-message');
  messageBoxes.forEach(function(box) {
    box.textContent = message;
    box.style.display = 'block';
    box.removeAttribute('hidden');
  });
}

function subscribe(reg) {
  if (!reg || !reg.pushManager) {
    if (subBtn) subBtn.disabled = false;
    showMessage('Service worker is not ready yet. Please retry.');
    return;
  }

  reg.pushManager.getSubscription().then(function(subscription) {
    const metaObj = document.querySelector('meta[name="django-webpush-vapid-key"]') || document.querySelector('meta[id="server-vapid-key"]');
    const applicationServerKey = metaObj ? metaObj.content : '';
    const options = { userVisibleOnly: true };

    if (applicationServerKey) {
      options.applicationServerKey = urlB64ToUint8Array(applicationServerKey);
    }

    reg.pushManager.subscribe(options).then(function(newSubscription) {
      postSubscribeObj('subscribe', newSubscription, function(response) {
        if (response && (response.status === 201 || response.status === 200)) {
          if (subBtn) {
            subBtn.textContent = (typeof gettext === 'function') ? gettext('Unsubscribe from Push Messaging') : 'Unsubscribe from Push Messaging';
            subBtn.disabled = false;
          }
          isPushEnabled = true;
          showMessage('Successfully subscribed to push notifications.');
        } else {
          if (subBtn) subBtn.disabled = false;
        }
      });
    }).catch(function(err) {
      console.error('Error while subscribing:', err);
      if (subBtn) subBtn.disabled = false;
      showMessage('Failed to subscribe: ' + (err.message || err));
    });
  });
}

function urlB64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

function unsubscribe(reg) {
  if (!reg || !reg.pushManager) {
    if (subBtn) subBtn.disabled = false;
    return;
  }

  reg.pushManager.getSubscription().then(function(subscription) {
    if (!subscription) {
      if (subBtn) subBtn.disabled = false;
      return;
    }

    postSubscribeObj('unsubscribe', subscription, function(response) {
      if (response && (response.status === 202 || response.status === 200)) {
        subscription.unsubscribe().then(function() {
          if (subBtn) {
            subBtn.textContent = (typeof gettext === 'function') ? gettext('Subscribe to Push Messaging') : 'Subscribe to Push Messaging';
            subBtn.disabled = false;
          }
          showMessage('Successfully unsubscribed from push notifications.');
          isPushEnabled = false;
        }).catch(function(err) {
          if (subBtn) subBtn.disabled = false;
        });
      }
    });
  });
}

function postSubscribeObj(statusType, subscription, callback) {
  const browser = (navigator.userAgent.match(/(firefox|msie|chrome|safari|trident|edg)/ig) || ['chrome'])[0].toLowerCase();
  const url = (subBtn && subBtn.dataset.url) ? subBtn.dataset.url : '/webpush/save_information';
  const data = {
    status_type: statusType,
    subscription: subscription.toJSON(),
    browser: browser,
    user_agent: navigator.userAgent,
    group: subBtn ? subBtn.dataset.group : ''
  };

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    credentials: 'include'
  }).then(callback).catch(function(err) {
    console.error('postSubscribeObj network error:', err);
    if (subBtn) subBtn.disabled = false;
  });
}
