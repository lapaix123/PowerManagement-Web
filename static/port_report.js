function updatePortReport() {
    const url = `/api/port_report/${meterNumber}?_=${Date.now()}`;
    console.log("Fetching port report from:", url);
    fetch(url)
      .then(response => response.json())
      .then(data => {
        if (data.error) {
          console.error("Error:", data.error);
        } else {
          document.getElementById('reportMeterNumber').innerText = data.meter_number;
          document.getElementById('reportLatestPurchasedPower').innerText = data.latest_purchased_power + " W";
          document.getElementById('reportCurrentPower').innerText = data.current_power + " W";
          document.getElementById('reportConsumedPower').innerText = data.consumed_power + " W";
          document.getElementById('reportPurchasedDate').innerText = data.purchased_date;
          document.getElementById('reportLatestDate').innerText = data.latest_date;
        }
      })
      .catch(err => {
        console.error("Error updating port report:", err);
      });
  }
  
  setInterval(updatePortReport, 2000);
  updatePortReport();
  