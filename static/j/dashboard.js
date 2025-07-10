// Ensure that your backend injects the meter number into the page; if not, you can adjust accordingly.
const meterNumber = "{{ user.meter_number }}";

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
// AJAX: Update Current Power Display
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
buyForSelect.addEventListener('change', (e) => {
  if (e.target.value === 'other') {
    otherMeterDiv.classList.remove('hidden');
  } else {
    otherMeterDiv.classList.add('hidden');
  }
});

// ---------------------
// Live Feedback for Other's Meter Existence
// ---------------------
const otherMeterInput = document.getElementById('other_meter_number');
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
function sendRelayCommand(state) {
  // Get the current displayed power (assumed format "x W")
  const currentPowerText = document.getElementById('currentPowerDisplay').innerText;
  const currentPower = Number(currentPowerText.split(" ")[0]);
  
  // If turning ON and power is 0, show toast and don't send command.
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
      showToast("Command failed", "red");
    });
}

document.getElementById("relayOnButton").addEventListener("click", () => {
  sendRelayCommand("on");
});
document.getElementById("relayOffButton").addEventListener("click", () => {
  sendRelayCommand("off");
});
