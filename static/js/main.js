
document.addEventListener("DOMContentLoaded", function () {
  // Navigation toggle
  var toggle = document.getElementById("navToggle");
  var links = document.getElementById("navLinks");

  if (toggle && links) {
    toggle.addEventListener("click", function () {
      links.classList.toggle("open");
    });
  }

  // Theme toggle — independent of navigation
 
  // Theme toggle
  var themeBtn = document.getElementById("themeToggle");
  var themeLink = document.getElementById("themeLink");

  if (themeBtn && themeLink) {
    function paintThemeIcon() {
      themeBtn.textContent = window.__theme === "dark" ? "☀️" : "🌙";
    }

    paintThemeIcon();

    themeBtn.addEventListener("click", function () {
      window.__theme = window.__theme === "dark" ? "light" : "dark";

      localStorage.setItem("theme", window.__theme);
      themeLink.href = window.__themeFiles[window.__theme];

      paintThemeIcon();
    });
  }

  // Keep the rest of your existing location-autocomplete
  // and image-preview code below this point.
});

  // Pan-India location autocomplete using OpenStreetMap Nominatim (free, no API key)
  document.querySelectorAll("[data-location-autocomplete]").forEach(function (searchInput) {
    var wrap = searchInput.closest(".autocomplete-wrap") || searchInput.parentElement;
    var list = wrap.querySelector("#location_suggestions") || wrap.querySelector(".autocomplete-list");
    var stateField = wrap.querySelector("#state");
    var districtField = wrap.querySelector("#district");
    var cityField = wrap.querySelector("#city");
    var areaField = wrap.querySelector("#area");
    var latField = wrap.querySelector("#latitude");
    var lonField = wrap.querySelector("#longitude");

    // If editing a report that already has a location, show it in the box
    if (stateField && stateField.value) {
      var parts = [areaField.value, cityField.value, districtField.value, stateField.value].filter(Boolean);
      searchInput.value = parts.join(", ");
    }

    var debounceTimer = null;
    var activeIndex = -1;

    function clearSelection() {
      stateField.value = ""; districtField.value = ""; cityField.value = "";
      areaField.value = ""; latField.value = ""; lonField.value = "";
    }

    function renderSuggestions(results) {
      list.innerHTML = "";
      activeIndex = -1;
      if (!results.length) { list.style.display = "none"; return; }
      results.forEach(function (place, idx) {
        var item = document.createElement("div");
        item.className = "autocomplete-item";
        item.textContent = place.display_name;
        item.addEventListener("click", function () { selectPlace(place); });
        list.appendChild(item);
      });
      list.style.display = "block";
    }

    function selectPlace(place) {
      var addr = place.address || {};
      stateField.value = addr.state || "";
      districtField.value = addr.state_district || addr.county || addr.city_district || addr.city || addr.town || "";
      cityField.value = addr.city || addr.town || addr.village || addr.municipality || addr.state_district || "";
      areaField.value = addr.suburb || addr.neighbourhood || addr.road || addr.hamlet || "";
      latField.value = place.lat || "";
      lonField.value = place.lon || "";
      searchInput.value = place.display_name;
      list.style.display = "none";
    }

    searchInput.addEventListener("input", function () {
      clearSelection();
      var query = searchInput.value.trim();
      clearTimeout(debounceTimer);
      if (query.length < 3) { list.style.display = "none"; return; }
      debounceTimer = setTimeout(function () {
        var url = "https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&countrycodes=in&limit=6&q=" + encodeURIComponent(query);
        fetch(url, { headers: { "Accept-Language": "en" } })
          .then(function (r) { return r.json(); })
          .then(renderSuggestions)
          .catch(function () { list.style.display = "none"; });
      }, 400);
    });

    // Keyboard navigation
    searchInput.addEventListener("keydown", function (e) {
      var items = list.querySelectorAll(".autocomplete-item");
      if (!items.length || list.style.display === "none") return;
      if (e.key === "ArrowDown") { e.preventDefault(); activeIndex = Math.min(activeIndex + 1, items.length - 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); activeIndex = Math.max(activeIndex - 1, 0); }
      else if (e.key === "Enter") { e.preventDefault(); if (activeIndex >= 0) items[activeIndex].click(); return; }
      else return;
      items.forEach(function (it, i) { it.classList.toggle("active", i === activeIndex); });
    });

    document.addEventListener("click", function (e) {
      if (!wrap.contains(e.target)) list.style.display = "none";
    });
  });

  // Live image preview for upload fields
  document.querySelectorAll("[data-image-preview]").forEach(function (input) {
    input.addEventListener("change", function () {
      var previewId = input.getAttribute("data-image-preview");
      var preview = document.getElementById(previewId);
      if (!preview || !input.files || !input.files[0]) return;
      var reader = new FileReader();
      reader.onload = function (e) {
        preview.src = e.target.result;
        preview.style.display = "block";
      };
      reader.readAsDataURL(input.files[0]);
    });
  });
