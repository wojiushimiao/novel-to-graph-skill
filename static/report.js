/* novel-to-graph-skill · report.js
 * 锚定: L3_接口契约与约束.md §3.2 报表前端功能接口
 * 实现: 搜索 / 节点点击 / 关系筛选 / 强度筛选 / 社群视图 / 导出MD / 导出JSON
 */
(function () {
  "use strict";

  var DATA = window.NOVEL_DATA || {};
  var nodes = DATA.nodes || [];
  var edges = DATA.edges || [];
  var communities = DATA.communities || {};
  var stats = DATA.stats || {};
  var topCentralities = DATA.top_centralities || {};
  var bridges = DATA.bridges || [];
  var orphans = DATA.orphans || [];

  var TYPE_LABELS = {
    character: "角色",
    location: "地点",
    event: "事件",
    item: "物品",
    rule: "规则",
    system: "系统",
  };

  var RELATION_LABELS = {
    located_in: "位于",
    participates_in: "参与",
    relates_to: "关联",
    evolves_to: "演化",
    causes: "导致",
    belongs_to: "属于",
    references: "引用",
  };

  var state = {
    selectedNode: null,
    activeCommunity: null,
    filterRelation: "",
    filterStrong: true,
    filterWeak: true,
    searchQuery: "",
    activeTab: "entities",
  };

  var cy = null;

  function init() {
    renderStats();
    initCytoscape();
    initToolbar();
    renderTabs();
  }

  function renderStats() {
    var bar = document.getElementById("stats-bar");
    if (!bar) return;
    var items = [
      ["节点", stats.node_count || nodes.length],
      ["边", stats.edge_count || edges.length],
      ["密度", (stats.density || 0).toFixed(4)],
      ["平均度", (stats.avg_degree || 0).toFixed(2)],
      ["孤立", stats.isolated_count || orphans.length],
      ["社群", Object.keys(communities).length],
      ["桥接", bridges.length],
    ];
    bar.innerHTML = items
      .map(function (it) {
        return '<div class="stat-item">' + it[0] + ":<strong>" + it[1] + "</strong></div>";
      })
      .join("");
  }

  function initCytoscape() {
    var cyContainer = document.getElementById("cy");
    if (!cyContainer || typeof cytoscape === "undefined") return;

    var cyNodes = nodes.map(function (n) {
      var cid = n.community != null ? n.community : -1;
      var color = getCommunityColor(cid);
      return {
        data: {
          id: n.id,
          label: n.label,
          type: n.type,
          community: cid,
          degree: n.degree_centrality || 0,
          betweenness: n.betweenness_centrality || 0,
          color: color,
        },
      };
    });

    var cyEdges = edges.map(function (e) {
      return {
        data: {
          id: e.id,
          source: e.source,
          target: e.target,
          relation_type: e.relation_type,
          strength: e.strength,
          weight: e.weight || (e.strength === "strong" ? 1.0 : 0.5),
          description: e.description || "",
        },
      };
    });

    cy = cytoscape({
      container: cyContainer,
      elements: { nodes: cyNodes, edges: cyEdges },
      style: [
        {
          selector: "node",
          style: {
            "background-color": function (ele) {
              return ele.data("color") || "#5B8FF9";
            },
            label: "data(label)",
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 6,
            "font-size": "10px",
            color: "#1f2937",
            width: function (ele) {
              var d = ele.data("degree") || 0;
              return Math.max(18, 18 + d * 30) + "px";
            },
            height: function (ele) {
              var d = ele.data("degree") || 0;
              return Math.max(18, 18 + d * 30) + "px";
            },
          },
        },
        {
          selector: "edge",
          style: {
            width: function (ele) {
              return ele.data("strength") === "strong" ? 2 : 1;
            },
            "line-color": function (ele) {
              return ele.data("strength") === "strong" ? "#E86452" : "#9CA3AF";
            },
            "target-arrow-color": function (ele) {
              return ele.data("strength") === "strong" ? "#E86452" : "#9CA3AF";
            },
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            opacity: 0.7,
          },
        },
        {
          selector: ":selected",
          style: {
            "border-width": 3,
            "border-color": "#FFD700",
            "border-opacity": 1,
          },
        },
        {
          selector: ".hidden",
          style: { display: "none" },
        },
        {
          selector: ".faded",
          style: { opacity: 0.15 },
        },
        {
          selector: ".highlighted",
          style: {
            "border-width": 2,
            "border-color": "#FFD700",
            opacity: 1,
          },
        },
      ],
      layout: {
        name: "cose",
        animate: true,
        "animationDuration": 300,
        nodeRepulsion: 8000,
        idealEdgeLength: 100,
        padding: 30,
      },
    });

    cy.on("tap", "node", function (evt) {
      selectNode(evt.target.id());
    });

    cy.on("tap", function (evt) {
      if (evt.target === cy) {
        clearSelection();
      }
    });
  }

  function getCommunityColor(cid) {
    var palette = [
      "#5B8FF9", "#5AD8A6", "#5D7092", "#F6BD16", "#E86452",
      "#6DC8EC", "#945FB9", "#FF9845", "#1E9493", "#FF99C3",
      "#286278", "#BCCUD9", "#54A0FF", "#48DBFB", "#1DD1A1",
      "#FECA57", "#FF6B6B", "#A29BFE", "#FDA1A1", "#FD79A8",
    ];
    if (cid == null || cid < 0) return "#9CA3AF";
    return palette[cid % palette.length];
  }

  function initToolbar() {
    var search = document.getElementById("search-input");
    if (search) {
      search.addEventListener("input", function () {
        state.searchQuery = this.value.toLowerCase().trim();
        applyFilters();
      });
    }

    var filterRel = document.getElementById("filter-relation");
    if (filterRel) {
      var relTypes = {};
      edges.forEach(function (e) {
        relTypes[e.relation_type] = true;
      });
      Object.keys(relTypes)
        .sort()
        .forEach(function (rt) {
          var opt = document.createElement("option");
          opt.value = rt;
          opt.textContent = RELATION_LABELS[rt] || rt;
          filterRel.appendChild(opt);
        });
      filterRel.addEventListener("change", function () {
        state.filterRelation = this.value;
        applyFilters();
      });
    }

    var cbStrong = document.getElementById("filter-strong");
    if (cbStrong) {
      cbStrong.addEventListener("change", function () {
        state.filterStrong = this.checked;
        applyFilters();
      });
    }
    var cbWeak = document.getElementById("filter-weak");
    if (cbWeak) {
      cbWeak.addEventListener("change", function () {
        state.filterWeak = this.checked;
        applyFilters();
      });
    }

    var btnReset = document.getElementById("btn-reset");
    if (btnReset) {
      btnReset.addEventListener("click", function () {
        if (search) search.value = "";
        if (filterRel) filterRel.value = "";
        if (cbStrong) cbStrong.checked = true;
        if (cbWeak) cbWeak.checked = true;
        state.searchQuery = "";
        state.filterRelation = "";
        state.filterStrong = true;
        state.filterWeak = true;
        state.activeCommunity = null;
        applyFilters();
        renderTabs();
      });
    }

    var btnMd = document.getElementById("btn-export-md");
    if (btnMd) {
      btnMd.addEventListener("click", exportMarkdown);
    }
    var btnJson = document.getElementById("btn-export-json");
    if (btnJson) {
      btnJson.addEventListener("click", exportJson);
    }
  }

  function applyFilters() {
    if (!cy) return;
    cy.nodes().removeClass("hidden faded highlighted");
    cy.edges().removeClass("hidden faded highlighted");

    var visibleNodes = new Set();
    var q = state.searchQuery;

    cy.nodes().forEach(function (n) {
      var matchSearch = !q || n.data("label").toLowerCase().indexOf(q) >= 0;
      var matchCommunity =
        state.activeCommunity == null || n.data("community") === state.activeCommunity;
      if (matchSearch && matchCommunity) {
        visibleNodes.add(n.id());
      } else {
        n.addClass("hidden");
      }
    });

    cy.edges().forEach(function (e) {
      var matchRel =
        !state.filterRelation || e.data("relation_type") === state.filterRelation;
      var matchStrength = true;
      if (e.data("strength") === "strong" && !state.filterStrong) matchStrength = false;
      if (e.data("strength") === "weak" && !state.filterWeak) matchStrength = false;
      var srcVisible = visibleNodes.has(e.data("source"));
      var tgtVisible = visibleNodes.has(e.data("target"));
      if (matchRel && matchStrength && srcVisible && tgtVisible) {
        // visible
      } else {
        e.addClass("hidden");
      }
    });

    if (state.activeTab === "entities") {
      renderEntityTable(Array.from(visibleNodes));
    }
  }

  function selectNode(nodeId) {
    state.selectedNode = nodeId;
    if (cy) {
      cy.nodes().removeClass("highlighted faded");
      cy.edges().removeClass("highlighted faded");
      var node = cy.getElementById(nodeId);
      node.addClass("highlighted");
      var neighbors = node.neighborhood();
      neighbors.nodes().addClass("highlighted");
      cy.nodes().not(node.union(neighbors.nodes())).addClass("faded");
      cy.edges().not(neighbors.edges().union(node.connectedEdges())).addClass("faded");
    }
    state.activeTab = "detail";
    renderTabs();
  }

  function clearSelection() {
    state.selectedNode = null;
    if (cy) {
      cy.nodes().removeClass("highlighted faded");
      cy.edges().removeClass("highlighted faded");
    }
    renderTabs();
  }

  function renderTabs() {
    var tabs = document.querySelectorAll(".tab");
    tabs.forEach(function (t) {
      t.classList.toggle("active", t.dataset.tab === state.activeTab);
    });
    tabs.forEach(function (t) {
      t.onclick = function () {
        state.activeTab = t.dataset.tab;
        renderTabs();
      };
    });

    var content = document.getElementById("tab-content");
    if (!content) return;

    if (state.activeTab === "entities") {
      renderEntityTable(null);
    } else if (state.activeTab === "communities") {
      renderCommunitiesTab(content);
    } else if (state.activeTab === "detail") {
      renderDetailTab(content);
    }
  }

  function renderEntityTable(visibleIds) {
    var content = document.getElementById("tab-content");
    if (!content) return;
    var list = nodes;
    if (visibleIds) {
      list = nodes.filter(function (n) {
        return visibleIds.indexOf(n.id) >= 0;
      });
    } else {
      var q = state.searchQuery;
      if (q) {
        list = nodes.filter(function (n) {
          return n.label.toLowerCase().indexOf(q) >= 0;
        });
      }
    }
    list = list.slice().sort(function (a, b) {
      return (b.degree_centrality || 0) - (a.degree_centrality || 0);
    });

    var html = '<table class="entity-table"><thead><tr>';
    html += "<th>名称</th><th>类型</th><th>度中心性</th><th>社群</th>";
    html += "</tr></thead><tbody>";
    if (list.length === 0) {
      html +=
        '</tbody></table><div class="empty-state">无匹配实体</div>';
      content.innerHTML = html;
      return;
    }
    list.forEach(function (n) {
      var cls = "type-" + n.type;
      var selected = state.selectedNode === n.id ? " selected" : "";
      html +=
        '<tr class="' + selected + '" data-id="' + n.id + '">';
      html += "<td>" + escapeHtml(n.label) + "</td>";
      html +=
        '<td><span class="type-badge ' +
        cls +
        '">' +
        (TYPE_LABELS[n.type] || n.type) +
        "</span></td>";
      html +=
        "<td>" + (n.degree_centrality || 0).toFixed(4) + "</td>";
      html += "<td>" + (n.community != null ? n.community + 1 : "-") + "</td>";
      html += "</tr>";
    });
    html += "</tbody></table>";
    content.innerHTML = html;

    var rows = content.querySelectorAll("tr[data-id]");
    rows.forEach(function (row) {
      row.onclick = function () {
        selectNode(this.getAttribute("data-id"));
      };
    });
  }

  function renderCommunitiesTab(content) {
    var keys = Object.keys(communities).sort(function (a, b) {
      return communities[b].node_count - communities[a].node_count;
    });
    if (keys.length === 0) {
      content.innerHTML = '<div class="empty-state">无社群数据</div>';
      return;
    }
    var html = '<div style="padding: 14px;">';
    keys.forEach(function (k) {
      var c = communities[k];
      var active = state.activeCommunity === parseInt(k, 10);
      var cls = "community-tag" + (active ? " active" : "");
      html +=
        '<span class="' + cls + '" data-cid="' + k + '" style="' +
        (active ? "background:" + c.color + ";color:white;border-color:" + c.color + ";" : "border-color:" + c.color + ";") +
        '">' +
        c.name + " (" + c.node_count + ")</span>";
    });
    html += "</div>";
    html += '<div style="padding: 0 14px 14px;">';
    if (topCentralities.degree) {
      html += "<h4 style='margin:8px 0 4px;'>度中心性 Top 10</h4><ol style='margin:0;padding-left:20px;font-size:12px;'>";
      topCentralities.degree.slice(0, 10).forEach(function (item) {
        var node = findNode(item.id);
        html +=
          "<li>" + (node ? escapeHtml(node.label) : item.id) +
          " (" + (item.score || 0).toFixed(4) + ")</li>";
      });
      html += "</ol>";
    }
    if (orphans.length > 0) {
      html += "<h4 style='margin:12px 0 4px;'>孤立实体 (" + orphans.length + ")</h4>";
      html += '<div style="font-size:12px;color:#6b7280;">';
      orphans.forEach(function (o, i) {
        if (i < 20) {
          var label = typeof o === "string" ? o : o.label || o.id;
          html += "<span style='display:inline-block;padding:2px 8px;margin:2px;background:#fafbfc;border:1px solid #e5e7eb;border-radius:10px;'>" + escapeHtml(label) + "</span>";
        }
      });
      if (orphans.length > 20) {
        html += "<span style='color:#9CA3AF;'>+" + (orphans.length - 20) + "...</span>";
      }
      html += "</div>";
    }
    html += "</div>";
    content.innerHTML = html;

    var tags = content.querySelectorAll(".community-tag");
    tags.forEach(function (tag) {
      tag.onclick = function () {
        var cid = parseInt(this.getAttribute("data-cid"), 10);
        state.activeCommunity = state.activeCommunity === cid ? null : cid;
        applyFilters();
        renderTabs();
      };
    });
  }

  function renderDetailTab(content) {
    if (!state.selectedNode) {
      content.innerHTML = '<div class="empty-state">点击图节点或表格行查看详情</div>';
      return;
    }
    var node = findNode(state.selectedNode);
    if (!node) {
      content.innerHTML = '<div class="empty-state">未找到节点</div>';
      return;
    }
    var html = '<div class="detail-panel">';
    html += "<h3>" + escapeHtml(node.label) + "</h3>";
    html += '<div class="field"><span class="field-label">ID:</span> <span class="field-value">' + escapeHtml(node.id) + "</span></div>";
    html += '<div class="field"><span class="field-label">类型:</span> <span class="type-badge type-' + node.type + '">' + (TYPE_LABELS[node.type] || node.type) + "</span></div>";
    html += '<div class="field"><span class="field-label">社群:</span> <span class="field-value">' + (node.community != null ? "社群" + (node.community + 1) : "-") + "</span></div>";
    html += '<div class="field"><span class="field-label">度中心性:</span> <span class="field-value">' + (node.degree_centrality || 0).toFixed(4) + "</span></div>";
    html += '<div class="field"><span class="field-label">介数中心性:</span> <span class="field-value">' + (node.betweenness_centrality || 0).toFixed(4) + "</span></div>";
    html += '<div class="field"><span class="field-label">特征向量:</span> <span class="field-value">' + (node.eigenvector_centrality || 0).toFixed(4) + "</span></div>";

    if (node.base_info) {
      html += "<h4>基础信息</h4>";
      var bi = node.base_info;
      if (bi.aliases && bi.aliases.length) {
        html += '<div class="field"><span class="field-label">别名:</span> <span class="field-value">' + bi.aliases.map(escapeHtml).join(", ") + "</span></div>";
      }
      if (bi.first_appearance) {
        html += '<div class="field"><span class="field-label">首次出现:</span> <span class="field-value">' + escapeHtml(bi.first_appearance) + "</span></div>";
      }
      if (bi.entity_description) {
        html += '<div class="field"><span class="field-label">描述:</span> <span class="field-value">' + escapeHtml(bi.entity_description) + "</span></div>";
      }
    }

    var relations = getNodeRelations(node.id);
    if (relations.length > 0) {
      html += "<h4>关系 (" + relations.length + ")</h4>";
      html += '<ul class="relations-list">';
      relations.forEach(function (r) {
        var target = findNode(r.target);
        var tlabel = target ? target.label : r.target;
        html += "<li><strong>" + (RELATION_LABELS[r.relation_type] || r.relation_type) +
          "</strong> → " + escapeHtml(tlabel) +
          " [" + (r.strength === "strong" ? "强" : "弱") + "]" +
          (r.description ? " " + escapeHtml(r.description) : "") + "</li>";
      });
      html += "</ul>";
    }

    if (node.coords) {
      html += "<h4>六维坐标</h4>";
      var c = node.coords;
      ["T", "L", "C", "E", "K"].forEach(function (k) {
        if (c[k] && (Array.isArray(c[k]) ? c[k].length : Object.keys(c[k]).length)) {
          var v = Array.isArray(c[k]) ? c[k].join(", ") : JSON.stringify(c[k]);
          html += '<div class="field"><span class="field-label">' + k + ':</span> <span class="field-value">' + escapeHtml(v) + "</span></div>";
        }
      });
      if (c.R) {
        html += '<div class="field"><span class="field-label">R:</span> <span class="field-value">' + escapeHtml(JSON.stringify(c.R)) + "</span></div>";
      }
    }

    html += "</div>";
    content.innerHTML = html;
  }

  function findNode(id) {
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].id === id) return nodes[i];
    }
    return null;
  }

  function getNodeRelations(nodeId) {
    return edges.filter(function (e) {
      return e.source === nodeId || e.target === nodeId;
    });
  }

  function exportMarkdown() {
    var lines = [];
    lines.push("# " + (DATA.title || "小说分析报表"));
    lines.push("");
    lines.push("生成时间: " + (DATA.generated_at || ""));
    lines.push("- 总实体: " + (stats.node_count || nodes.length));
    lines.push("- 总关系: " + (stats.edge_count || edges.length));
    lines.push("- 图密度: " + (stats.density || 0).toFixed(4));
    lines.push("- 孤立实体: " + (stats.isolated_count || orphans.length));
    lines.push("");
    var grouped = {};
    nodes.forEach(function (n) {
      if (!grouped[n.type]) grouped[n.type] = [];
      grouped[n.type].push(n);
    });
    Object.keys(grouped).forEach(function (t) {
      lines.push("## " + (TYPE_LABELS[t] || t) + " (" + grouped[t].length + ")");
      grouped[t].forEach(function (n) {
        lines.push("### " + n.label);
        lines.push("- ID: " + n.id);
        if (n.base_info && n.base_info.entity_description) {
          lines.push("- 描述: " + n.base_info.entity_description);
        }
        var rels = getNodeRelations(n.id);
        if (rels.length > 0) {
          lines.push("- 关系:");
          rels.forEach(function (r) {
            var t2 = findNode(r.target);
            lines.push("  - " + (RELATION_LABELS[r.relation_type] || r.relation_type) + " → " + (t2 ? t2.label : r.target) + " [" + r.strength + "]");
          });
        }
        lines.push("");
      });
    });
    download("report.md", lines.join("\n"), "text/markdown");
  }

  function exportJson() {
    var payload = {
      title: DATA.title,
      generated_at: DATA.generated_at,
      stats: stats,
      nodes: nodes,
      edges: edges,
      communities: communities,
      top_centralities: topCentralities,
      bridges: bridges,
      orphans: orphans,
    };
    download("report.json", JSON.stringify(payload, null, 2), "application/json");
  }

  function download(filename, content, mime) {
    var blob = new Blob([content], { type: mime + ";charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
