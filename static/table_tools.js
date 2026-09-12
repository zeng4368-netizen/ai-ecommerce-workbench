(function () {
  function normalizeText(value) {
    return (value || "").toString().toLowerCase().trim();
  }

  function getCellText(row, index) {
    const cell = row.cells[index];
    return cell ? cell.textContent.trim() : "";
  }

  function parseNumber(value) {
    const cleaned = value.replace(/[,%]/g, "").replace(/万/g, "0000").trim();
    if (!cleaned || cleaned === "-") return Number.NaN;
    const num = Number(cleaned);
    return Number.isFinite(num) ? num : Number.NaN;
  }

  function compareValues(a, b, direction) {
    const aNum = parseNumber(a);
    const bNum = parseNumber(b);
    let result;
    if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) {
      result = aNum - bNum;
    } else {
      result = a.localeCompare(b, "zh-Hans-CN", { numeric: true, sensitivity: "base" });
    }
    return direction === "asc" ? result : -result;
  }

  function csvEscape(value) {
    const text = (value || "").toString().replace(/\r?\n/g, " ").trim();
    return `"${text.replace(/"/g, '""')}"`;
  }

  function downloadCsv(table, visibleRows, title) {
    const headers = Array.from(table.tHead.rows[0].cells).map((cell) => csvEscape(cell.textContent));
    const lines = [headers.join(",")];
    visibleRows.forEach((row) => {
      lines.push(Array.from(row.cells).map((cell) => csvEscape(cell.textContent)).join(","));
    });
    const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const safeTitle = title.replace(/[^\w\u4e00-\u9fa5-]+/g, "_");
    link.href = url;
    link.download = `${safeTitle || "table"}_filtered.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function makeFilterRow(table, state) {
    const filterRow = document.createElement("tr");
    filterRow.className = "column-filter-row";
    Array.from(table.tHead.rows[0].cells).forEach((header, index) => {
      const cell = document.createElement("th");
      const select = document.createElement("select");
      select.dataset.columnIndex = index.toString();

      const allOption = document.createElement("option");
      allOption.value = "";
      allOption.textContent = "全部";
      select.appendChild(allOption);

      const values = Array.from(new Set(state.allRows.map((row) => getCellText(row, index))))
        .sort((a, b) => a.localeCompare(b, "zh-Hans-CN", { numeric: true, sensitivity: "base" }));

      values.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value || "(空)";
        select.appendChild(option);
      });

      select.addEventListener("change", () => {
        state.columnFilters[index] = select.value;
        applyState(state);
      });
      cell.appendChild(select);
      filterRow.appendChild(cell);
    });
    table.tHead.appendChild(filterRow);
  }

  function updateHeaderSortState(state) {
    Array.from(state.table.tHead.rows[0].cells).forEach((header, index) => {
      header.classList.remove("sort-asc", "sort-desc");
      header.removeAttribute("aria-sort");
      if (state.sortColumn === index) {
        header.classList.add(state.sortDirection === "asc" ? "sort-asc" : "sort-desc");
        header.setAttribute("aria-sort", state.sortDirection === "asc" ? "ascending" : "descending");
      }
    });
  }

  function applyState(state) {
    const globalTerm = normalizeText(state.searchInput.value);
    const filtered = state.allRows.filter((row) => {
      const rowText = normalizeText(row.textContent);
      if (globalTerm && !rowText.includes(globalTerm)) return false;

      for (const [index, value] of Object.entries(state.columnFilters)) {
        if (value && getCellText(row, Number(index)) !== value) {
          return false;
        }
      }
      return true;
    });

    if (state.sortColumn !== null) {
      filtered.sort((a, b) => {
        return compareValues(
          getCellText(a, state.sortColumn),
          getCellText(b, state.sortColumn),
          state.sortDirection
        );
      });
    }

    const tbody = state.table.tBodies[0];
    filtered.forEach((row) => tbody.appendChild(row));
    state.allRows.forEach((row) => {
      row.hidden = !filtered.includes(row);
    });

    state.visibleRows = filtered;
    state.countNode.textContent = `显示 ${filtered.length.toLocaleString()} / ${state.allRows.length.toLocaleString()} 行`;
    updateHeaderSortState(state);
  }

  function resetState(state) {
    state.searchInput.value = "";
    state.columnFilters = {};
    state.sortColumn = null;
    state.sortDirection = "asc";
    Array.from(state.table.tHead.querySelectorAll(".column-filter-row select")).forEach((select) => {
      select.value = "";
    });
    const tbody = state.table.tBodies[0];
    state.originalRows.forEach((row) => tbody.appendChild(row));
    state.allRows.forEach((row) => {
      row.hidden = false;
    });
    state.visibleRows = state.allRows.slice();
    state.countNode.textContent = `显示 ${state.visibleRows.length.toLocaleString()} / ${state.allRows.length.toLocaleString()} 行`;
    updateHeaderSortState(state);
  }

  function setupTable(section, sectionIndex) {
    const table = section.querySelector("table.data-table");
    const wrap = section.querySelector(".table-wrap");
    if (!table || !wrap || !table.tHead || !table.tBodies.length) return;

    const rows = Array.from(table.tBodies[0].rows);
    if (!rows.length) return;

    const title = section.querySelector(".section-heading h2")?.textContent.trim() || `表格${sectionIndex + 1}`;

    const toolbar = document.createElement("div");
    toolbar.className = "table-toolbar";
    toolbar.innerHTML = `
      <div class="table-search">
        <label>
          <span>本表搜索</span>
          <input type="search" placeholder="输入关键词筛选当前模块">
        </label>
      </div>
      <div class="table-actions">
        <span class="table-count"></span>
        <button type="button" class="table-reset">重置本表</button>
        <button type="button" class="table-export">导出当前筛选</button>
      </div>
    `;
    section.insertBefore(toolbar, wrap);

    const state = {
      table,
      allRows: rows.slice(),
      originalRows: rows.slice(),
      visibleRows: rows.slice(),
      columnFilters: {},
      sortColumn: null,
      sortDirection: "asc",
      searchInput: toolbar.querySelector('input[type="search"]'),
      countNode: toolbar.querySelector(".table-count"),
    };

    makeFilterRow(table, state);

    Array.from(table.tHead.rows[0].cells).forEach((header, index) => {
      header.tabIndex = 0;
      header.classList.add("sortable");
      header.title = "点击排序";
      const sort = () => {
        if (state.sortColumn === index) {
          state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
        } else {
          state.sortColumn = index;
          state.sortDirection = "asc";
        }
        applyState(state);
      };
      header.addEventListener("click", sort);
      header.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sort();
        }
      });
    });

    state.searchInput.addEventListener("input", () => applyState(state));
    toolbar.querySelector(".table-reset").addEventListener("click", () => resetState(state));
    toolbar.querySelector(".table-export").addEventListener("click", () => {
      downloadCsv(table, state.visibleRows, title);
    });

    resetState(state);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".table-section").forEach(setupTable);
  });
})();
