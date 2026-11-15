/* Earth Analog Finder: optional enhancements (zoom/pan, tooltips, sortable tables).
   Vanilla JS, no dependencies. All content stays readable without this file. */
(function () {
  "use strict";

  function initMap(svg) {
    var full = svg.viewBox.baseVal;
    var W = full.width, H = full.height;
    var vb = { x: 0, y: 0, w: W, h: H };
    function apply() { svg.setAttribute("viewBox", vb.x + " " + vb.y + " " + vb.w + " " + vb.h); }
    function clamp() {
      vb.w = Math.min(Math.max(vb.w, W / 16), W); vb.h = vb.w * H / W;
      vb.x = Math.min(Math.max(vb.x, 0), W - vb.w); vb.y = Math.min(Math.max(vb.y, 0), H - vb.h);
    }
    function zoom(f, cx, cy) {
      if (cx === undefined) { cx = vb.x + vb.w / 2; cy = vb.y + vb.h / 2; }
      vb.x = cx - (cx - vb.x) * f; vb.y = cy - (cy - vb.y) * f; vb.w *= f; clamp(); apply();
    }
    function toSvg(e) {
      var r = svg.getBoundingClientRect();
      return { x: vb.x + (e.clientX - r.left) / r.width * vb.w, y: vb.y + (e.clientY - r.top) / r.height * vb.h };
    }
    svg.addEventListener("wheel", function (e) {
      e.preventDefault(); var p = toSvg(e); zoom(e.deltaY < 0 ? 0.8 : 1.25, p.x, p.y);
    }, { passive: false });
    var drag = null;
    svg.addEventListener("pointerdown", function (e) {
      if (e.target.closest && e.target.closest("a")) return;
      drag = { x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y }; svg.setPointerCapture(e.pointerId);
    });
    svg.addEventListener("pointermove", function (e) {
      if (!drag) return; var r = svg.getBoundingClientRect();
      vb.x = drag.vx - (e.clientX - drag.x) / r.width * vb.w;
      vb.y = drag.vy - (e.clientY - drag.y) / r.height * vb.h; clamp(); apply();
    });
    svg.addEventListener("pointerup", function () { drag = null; });
    var controls = document.querySelector(".map-controls");
    if (controls) {
      controls.hidden = false;
      controls.addEventListener("click", function (e) {
        var z = e.target.getAttribute("data-zoom");
        if (z === "in") zoom(0.66); else if (z === "out") zoom(1.5);
        else if (z === "reset") { vb = { x: 0, y: 0, w: W, h: H }; apply(); }
      });
    }
    var tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true;
    document.body.appendChild(tip);
    var marks = svg.querySelectorAll(".marker");
    for (var i = 0; i < marks.length; i++) {
      marks[i].addEventListener("pointerenter", function (e) {
        var a = e.currentTarget, rank = a.getAttribute("data-rank");
        tip.textContent = (rank ? "#" + rank + " " : "") + a.getAttribute("data-name") +
          " · " + a.getAttribute("data-score") + " · limiting: " + a.getAttribute("data-limiting");
        tip.hidden = false;
      });
      marks[i].addEventListener("pointermove", function (e) {
        tip.style.left = (e.clientX + 12) + "px"; tip.style.top = (e.clientY + 12) + "px";
      });
      marks[i].addEventListener("pointerleave", function () { tip.hidden = true; });
    }
  }

  function cellValue(td, numeric) {
    var t = td.textContent.trim();
    if (!numeric) return t.toLowerCase();
    var v = parseFloat(t.replace(/[^0-9.\-]/g, ""));
    return isNaN(v) ? -Infinity : v;
  }

  function initSort(table) {
    var heads = table.querySelectorAll("thead th");
    heads.forEach(function (th, col) {
      th.setAttribute("data-sort", th.getAttribute("data-sort") || "text");
      th.addEventListener("click", function () {
        var numeric = th.getAttribute("data-sort") === "num";
        var asc = !th.classList.contains("sorted-asc");
        heads.forEach(function (h) { h.classList.remove("sorted-asc", "sorted-desc"); });
        th.classList.add(asc ? "sorted-asc" : "sorted-desc");
        var body = table.tBodies[0], rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) {
          var x = cellValue(a.cells[col], numeric), y = cellValue(b.cells[col], numeric);
          return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var svg = document.getElementById("map");
    if (svg && svg.viewBox && svg.viewBox.baseVal) initMap(svg);
    document.querySelectorAll("table.sortable").forEach(initSort);
  });
})();
