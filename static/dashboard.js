// Use the global meterNumber variable defined in the HTML

// ---------------------
// Toast Notification Logic
// ---------------------
let lastRedToastTime = 0;
let lastYellowToastTime = 0;
let lastToastTrigger = 0;
let showingToast = false;
let toastStartTime = 0;
let toastMessage = "";

function showToast(message, bgColor) {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.style.backgroundColor = bgColor;
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => { toast.remove(); }, 3000);
}

function checkPowerCondition(currentPower) {
  const now = Date.now();
  if (currentPower == 0) {
    if (now - lastRedToastTime > 3000) {
      showToast("Power is 0, please buy electricity!", "red");
      lastRedToastTime = now;
    }
  } else if (currentPower < 3) {
    if (now - lastYellowToastTime > 5000) {
      showToast("Buy new Power almost over!", "orange");
      lastYellowToastTime = now;
    }
  }
}

// ---------------------
// Update Current Power Display via AJAX
// ---------------------
function updateCurrentPower() {
  fetch(`/api/current_power/${meterNumber}`)
    .then(response => response.json())
    .then(data => {
      if (data.error) {
        console.error(data.error);
      } else {
        const currentPower = data.current_power;
        document.getElementById('currentPowerDisplay').innerText = `${currentPower} W`;
        checkPowerCondition(currentPower);
      }
    })
    .catch(err => { console.error("Error fetching current power:", err); });
}

setInterval(updateCurrentPower, 1000);
updateCurrentPower();

// ---------------------
// Refresh Button for Sensor Reading
// ---------------------
const refreshBtn = document.getElementById('refreshBtn');
const ajaxResult = document.getElementById('ajaxResult');
refreshBtn.addEventListener('click', () => {
  fetch(`/api/latest-reading/${meterNumber}`)
    .then(response => response.json())
    .then(data => {
      if (data.error) {
        ajaxResult.innerText = data.error;
      } else {
        ajaxResult.innerText = `Voltage: ${data.voltage} V, Current: ${data.current} A, Power: ${data.power} W (at ${data.reading_time})`;
      }
    })
    .catch(err => { ajaxResult.innerText = "Error fetching data."; });
});

// ---------------------
// Toggle Other Meter Input in Buy Electricity Form
// ---------------------
const buyForSelect = document.getElementById('buy_for');
const otherMeterDiv = document.getElementById('otherMeterDiv');
const otherMeterInput = document.getElementById('other_meter_number');

buyForSelect.addEventListener('change', (e) => {
  if (e.target.value === 'other') {
    otherMeterDiv.classList.remove('hidden');
    otherMeterInput.required = true;
  } else {
    otherMeterDiv.classList.add('hidden');
    otherMeterInput.required = false;
  }
});

// ---------------------
// Live Feedback for Other's Meter Number Existence
// ---------------------
const meterFeedback = document.getElementById('meterFeedback');
if (otherMeterInput) {
  otherMeterInput.addEventListener('input', () => {
    const meterVal = otherMeterInput.value.trim();
    if (meterVal.length === 0) {
      meterFeedback.innerText = '';
      return;
    }
    fetch(`/admin/check_meter?meter=${encodeURIComponent(meterVal)}`)
      .then(response => response.json())
      .then(data => {
        if (data.exists) {
          meterFeedback.innerText = `Meter exists for user: ${data.username}`;
          meterFeedback.classList.remove('text-red-600');
          meterFeedback.classList.add('text-green-600');
        } else {
          meterFeedback.innerText = 'No user found for that meter number.';
          meterFeedback.classList.remove('text-green-600');
          meterFeedback.classList.add('text-red-600');
        }
      })
      .catch(err => {
        meterFeedback.innerText = 'Error checking meter.';
        meterFeedback.classList.remove('text-green-600');
        meterFeedback.classList.add('text-red-600');
      });
  });
}

// ---------------------
// Relay Control via Web Buttons
// ---------------------
// ---------------------
// Relay Control via Web Buttons
// ---------------------
function sendRelayCommand(state) {
  const currentPowerElement = document.getElementById("currentPowerDisplay");
  
  if (!currentPowerElement) {
    console.error("Error: Power display element not found.");
    showToast("System error: Power display missing!", "red");
    return;
  }

  // Get the current displayed power value safely
  const currentPowerText = currentPowerElement.innerText.trim();
  const currentPower = parseFloat(currentPowerText.split(" ")[0]); // Extract numeric power value

  if (isNaN(currentPower)) {
    console.error("Error: Invalid power value.");
    showToast("Error fetching power value!", "red");
    return;
  }

  // Prevent relay from turning ON if power is 0
  if (state === "on" && currentPower === 0) {
    showToast("Not enough power to turn relay ON!", "red");
    return;
  }

  fetch("/api/relay_control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ meter_number: meterNumber, state: state })
  })
    .then(response => response.json())
    .then(data => {
      if (data.error) {
        showToast(data.error, "red");
      } else {
        showToast(data.message, "green");
      }
    })
    .catch(err => {
      console.error("Error sending relay command:", err);
      showToast("Failed to send relay command", "red");
    });
}

// Attach event listeners to buttons
document.getElementById("relayOnButton")?.addEventListener("click", () => sendRelayCommand("on"));
document.getElementById("relayOffButton")?.addEventListener("click", () => sendRelayCommand("off"));

