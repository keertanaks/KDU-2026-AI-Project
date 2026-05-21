"""Variant card component — renders score, images, zone pills, and rationale."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from utils.logger import get_logger

ZONE_COLORS: dict[str, str] = {
    "cooking": "#FF6B6B",
    "cleaning": "#4ECDC4",
    "cooling": "#45B7D1",
    "preparation": "#FFD700",
    "default": "#95A5A6",
}

logger = get_logger(__name__)


def _get(obj: object, key: str, default: Any = None) -> Any:
    """Unified access for dataclass and dict results."""
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)  # type: ignore[union-attr]


def score_badge(score: float) -> str:
    """Return HTML badge string for the given score."""
    color = "#38A169" if score > 0.8 else "#D69E2E" if score >= 0.6 else "#E53E3E"
    emoji = "🟢" if score > 0.8 else "🟡" if score >= 0.6 else "🔴"
    return (
        f'<span style="color:{color};font-weight:700;font-size:1.3rem">{emoji} {score:.2f}</span>'
    )


def zone_pills_html(layout_dict: dict[str, Any]) -> str:
    """Return HTML zone pill spans for items in layout_dict."""
    zone_counts: Counter[str] = Counter(
        item.get("zone_type", "unknown")
        for item in layout_dict.values()
        if not item.get("is_wall")
        and not item.get("is_floor")
        and not item.get("is_door")
        and not item.get("is_window")
    )
    return " ".join(
        f'<span style="background:{ZONE_COLORS.get(z, ZONE_COLORS["default"])};'
        f"color:#0D1117;padding:3px 10px;border-radius:12px;"
        f'font-size:0.8rem;margin:2px;display:inline-block">'
        f"{z.title()} ({n})</span>"
        for z, n in sorted(zone_counts.items())
    )


def _build_threejs_html(
    v_id: str, family: str, layout: dict[str, Any], env: dict[str, Any]
) -> str:
    floor_data = env.get("floor", {})
    walls_data = env.get("wall", [])
    floor_dims = floor_data.get("dimensions_mm", {})
    floor_x = float(floor_dims.get("width", 3600))
    floor_y = float(floor_dims.get("depth", 3200))

    items = []
    for key, item in layout.items():
        if any(item.get(f"is_{t}") for t in ("wall", "floor", "door", "window")):
            continue
        pos = item.get("position_mm") or {}
        items.append(
            {
                "id": key,
                "name": item.get("product_id", item.get("name", key)),
                "zone": item.get("zone_type", "storage"),
                "x": float(pos.get("x", 0)),
                "y": float(pos.get("y", 0)),
                "z": float(pos.get("z", 0)),
                "w": float(item.get("width_mm", 600)),
                "d": float(item.get("depth_mm", 600)),
                "h": float(item.get("height_mm", 900)),
            }
        )

    walls = []
    for wall in walls_data:
        dims = wall.get("dimensions_mm", {})
        pos = wall.get("position_mm", {})
        walls.append(
            {
                "x": float(pos.get("x", 0)),
                "y": float(pos.get("y", 0)),
                "w": float(dims.get("width", floor_x)),
                "d": float(dims.get("depth", 100)),
                "h": float(dims.get("height", 2500)),
            }
        )

    payload = json.dumps(
        {
            "floor_x": floor_x,
            "floor_y": floor_y,
            "walls": walls,
            "items": items,
        }
    )
    title = f"{v_id} — {family}"
    return _THREEJS_TEMPLATE.replace("__PAYLOAD__", payload).replace("__TITLE__", title)


_THREEJS_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0D1117; overflow:hidden; font-family:monospace; }
#info { position:absolute; top:8px; left:10px; color:#8B949E; font-size:11px; user-select:none; pointer-events:none; }
#titlebar { position:absolute; top:8px; right:10px; color:#00D4B1; font-size:12px; font-weight:bold; user-select:none; pointer-events:none; }
#tip { position:absolute; padding:4px 10px; background:rgba(0,212,177,0.12); border:1px solid #00D4B1;
  color:#E6EDF3; font-size:11px; border-radius:4px; pointer-events:none; display:none; white-space:nowrap; }
</style>
</head>
<body>
<div id="info">Drag: rotate &nbsp;·&nbsp; Scroll: zoom &nbsp;·&nbsp; Right-drag: pan</div>
<div id="titlebar">__TITLE__</div>
<div id="tip"></div>
<script type="importmap">
{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const DATA = __PAYLOAD__;
const S = 1 / 100; // mm → scene units (1 unit = 10 cm)

// ── Scene ──────────────────────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0D1117);
scene.fog = new THREE.FogExp2(0x151C28, 0.007);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.15;
document.body.appendChild(renderer.domElement);

const W = DATA.floor_x * S, D = DATA.floor_y * S, RH = 25;
const cx = W / 2, cz = D / 2;

const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 300);
camera.position.set(cx + W * 0.6, RH * 1.05, cz + D * 0.8);
camera.lookAt(cx, RH * 0.2, cz);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(cx, RH * 0.2, cz);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.minDistance = 4;
controls.maxDistance = 110;
controls.maxPolarAngle = Math.PI * 0.87;
controls.update();

// ── Lights ─────────────────────────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xFFFFFF, 0.38));
scene.add(new THREE.HemisphereLight(0xFFF5E0, 0x303840, 0.55));

const sun = new THREE.DirectionalLight(0xFFF8EC, 1.2);
sun.position.set(cx + 14, 34, cz + 20);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.near = 0.5;
sun.shadow.camera.far = 130;
sun.shadow.camera.left = -50; sun.shadow.camera.right = 50;
sun.shadow.camera.top  =  50; sun.shadow.camera.bottom = -50;
sun.shadow.bias = -0.001;
scene.add(sun);

const fill = new THREE.DirectionalLight(0xC0D8FF, 0.45);
fill.position.set(cx - 20, 18, cz - 14);
scene.add(fill);

// Recessed ceiling spots
for (let lx = W * 0.25; lx <= W * 0.76; lx += W * 0.5) {
  for (let lz = D * 0.25; lz <= D * 0.76; lz += D * 0.5) {
    const pt = new THREE.PointLight(0xFFF8E8, 0.45, 22);
    pt.position.set(lx, RH - 0.4, lz);
    scene.add(pt);
  }
}

// ── Materials ──────────────────────────────────────────────────────────────
const M = {
  floor:    new THREE.MeshLambertMaterial({ color: 0xEEDFC6 }),
  wall:     new THREE.MeshLambertMaterial({ color: 0xF0EAE0 }),
  baseCab:  new THREE.MeshLambertMaterial({ color: 0xC4903A }),
  wallCab:  new THREE.MeshLambertMaterial({ color: 0xDFBB80 }),
  tallCab:  new THREE.MeshLambertMaterial({ color: 0x7B5C3A }),
  counter:  new THREE.MeshPhongMaterial({ color: 0x6B5A4E, shininess: 75, specular: 0x3A3A3A }),
  fridge:   new THREE.MeshPhongMaterial({ color: 0xD2D2D2, shininess: 85, specular: 0x909090 }),
  stove:    new THREE.MeshPhongMaterial({ color: 0x252525, shininess: 55, specular: 0x606060 }),
  hood:     new THREE.MeshPhongMaterial({ color: 0xB8B8B8, shininess: 100, specular: 0xBBBBBB }),
  sink:     new THREE.MeshPhongMaterial({ color: 0xA8A8A8, shininess: 110, specular: 0xC0C0C0 }),
  dishwash: new THREE.MeshPhongMaterial({ color: 0xCCCCCC, shininess: 70, specular: 0x888888 }),
  micro:    new THREE.MeshLambertMaterial({ color: 0x282828 }),
  generic:  new THREE.MeshLambertMaterial({ color: 0xB89060 }),
};

// ── Box helper (corner-positioned) ────────────────────────────────────────
function addBox(wx, wy, wz, mat, ox, oy, oz, cast = true, recv = true) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(wx, wy, wz), mat);
  mesh.position.set(ox + wx / 2, oy + wy / 2, oz + wz / 2);
  mesh.castShadow = cast;
  mesh.receiveShadow = recv;
  scene.add(mesh);
  return mesh;
}

// ── Item classifier ────────────────────────────────────────────────────────
function classify(item) {
  const n = (item.name || '').toLowerCase();
  const z = (item.zone || '').toLowerCase();
  if (n.includes('fridge') || n.includes('refrigerator') || z === 'cooling') return 'fridge';
  if (n.includes('oven') || n.includes('stove') || n.includes('range') || n.includes('hob')) return 'stove';
  if (n.includes('hood') || n.includes('extractor')) return 'hood';
  if (n.includes('sink')) return 'sink';
  if (n.includes('dishwasher') || n.includes('_dw')) return 'dishwash';
  if (n.includes('microwave') || n.includes('_mw')) return 'micro';
  if (n.includes('wall_cab') || n.includes('wallcab') || n.includes('upper')) return 'wallCab';
  if (n.includes('tall') || n.includes('pantry') || n.includes('larder') || n.includes('tower')) return 'tallCab';
  if (item.z >= 1000 && item.h <= 900) return 'wallCab';
  if (z === 'storage' && item.h >= 1800) return 'tallCab';
  return 'baseCab';
}

// ── Floor ──────────────────────────────────────────────────────────────────
const floorMesh = new THREE.Mesh(new THREE.PlaneGeometry(W, D), M.floor);
floorMesh.rotation.x = -Math.PI / 2;
floorMesh.position.set(cx, 0, cz);
floorMesh.receiveShadow = true;
scene.add(floorMesh);

// Tile grout lines
const grid = new THREE.GridHelper(Math.max(W, D) * 1.3, Math.round(Math.max(W, D) / 4), 0xC4B090, 0xC4B090);
grid.position.set(cx, 0.004, cz);
grid.material.opacity = 0.3;
grid.material.transparent = true;
scene.add(grid);

// ── Walls ──────────────────────────────────────────────────────────────────
const WT = 0.15;
if (DATA.walls.length > 0) {
  for (const w of DATA.walls) {
    addBox(w.w * S, w.h * S, w.d * S, M.wall, w.x * S, 0, w.y * S, false, true);
  }
} else {
  // Fallback: 4 walls from floor footprint
  addBox(W, RH, WT, M.wall, 0,      0, 0,      false, true); // north
  addBox(W, RH, WT, M.wall, 0,      0, D - WT, false, true); // south
  addBox(WT, RH, D, M.wall, 0,      0, 0,      false, true); // west
  addBox(WT, RH, D, M.wall, W - WT, 0, 0,      false, true); // east
}

// ── Kitchen items ──────────────────────────────────────────────────────────
const COUNTER_H = 0.25;
const COUNTER_OVERHANG = 0.15;
const pickable = [];

for (const item of DATA.items) {
  const type = classify(item);
  const mat  = M[type] || M.generic;
  // Coordinate remap: kitchen(x,y,z) → scene(x, z_kitchen→Y, y_kitchen→Z)
  const sx = item.x * S, sy = item.z * S, sz = item.y * S;
  const sw = item.w * S, sh = item.h * S, sd = item.d * S;

  const mesh = addBox(sw, sh, sd, mat, sx, sy, sz);
  mesh.userData = { label: item.name, zone: item.zone, type };
  pickable.push(mesh);

  // Stone countertop slab on base-level cabinets
  const isBaseLevel = item.z === 0 && item.h >= 700 && item.h <= 1060;
  const isAppliance = ['fridge', 'stove', 'hood', 'sink', 'dishwash', 'micro'].includes(type);
  if (isBaseLevel && !isAppliance) {
    const ct = addBox(
      sw + COUNTER_OVERHANG * 2, COUNTER_H, sd + COUNTER_OVERHANG,
      M.counter,
      sx - COUNTER_OVERHANG, sy + sh, sz - COUNTER_OVERHANG,
      false, true
    );
    ct.userData = { label: item.name + ' — countertop', zone: item.zone, type: 'counter' };
    pickable.push(ct);
  }

  // Stainless hob plate on stove
  if (type === 'stove' && isBaseLevel) {
    const hob = addBox(sw * 0.88, 0.06, sd * 0.88, M.counter, sx + sw * 0.06, sy + sh, sz + sd * 0.06, false, false);
    hob.userData = { label: item.name + ' — hob', zone: item.zone, type: 'stove' };
    pickable.push(hob);
  }

  // Stainless basin on sink
  if (type === 'sink' && isBaseLevel) {
    const basin = addBox(sw * 0.6, 0.18, sd * 0.7, M.sink, sx + sw * 0.2, sy + sh - 0.15, sz + sd * 0.15, false, false);
    basin.userData = { label: item.name + ' — basin', zone: item.zone, type: 'sink' };
    pickable.push(basin);
  }
}

// ── Hover tooltip ──────────────────────────────────────────────────────────
const raycaster = new THREE.Raycaster();
const mouse     = new THREE.Vector2();
const tip       = document.getElementById('tip');

window.addEventListener('mousemove', (e) => {
  mouse.x = (e.clientX / window.innerWidth)  *  2 - 1;
  mouse.y = (e.clientY / window.innerHeight) * -2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(pickable);
  if (hits.length && hits[0].object.userData.label) {
    const d = hits[0].object.userData;
    tip.style.display = 'block';
    tip.style.left    = (e.clientX + 14) + 'px';
    tip.style.top     = (e.clientY -  6) + 'px';
    tip.textContent   = d.label + (d.zone ? '  ·  ' + d.zone : '');
  } else {
    tip.style.display = 'none';
  }
});

// ── Render loop ────────────────────────────────────────────────────────────
(function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
})();

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
</script>
</body>
</html>"""


def render_variant_card(v: Any, index: int) -> None:
    """Render a full variant card with score, images, zones, violations, and rationale."""
    v_id = str(_get(v, "id") or "")
    family = str(_get(v, "family") or "")
    score = float(_get(v, "score") or 0.0)
    count = int(_get(v, "placement_count") or 0)
    violations = list(_get(v, "violations") or [])
    rationale = list(_get(v, "rationale") or [])
    layout = dict(_get(v, "layout") or {})

    st.markdown(
        f'<div class="card">'
        f"{score_badge(score)}"
        f'<span style="color:#8B949E;margin:0 12px">·</span>'
        f'<span style="color:#E6EDF3;font-weight:600">{v_id} -- {family}</span>'
        f'<span style="color:#8B949E;margin-left:12px;font-size:0.9rem">'
        f"{count} items placed</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    view = st.radio(
        "View",
        ["2D Top View", "3D View"],
        horizontal=True,
        key=f"view_{v_id}_{index}",
        label_visibility="collapsed",
    )
    img_path = f"renders/{v_id}_top.png" if view == "2D Top View" else f"renders/{v_id}_3d.png"
    if Path(img_path).exists():
        st.image(img_path, width="stretch")
    else:
        st.markdown(
            '<div style="background:#1C2128;border:1px dashed #30363D;border-radius:6px;'
            'padding:40px;text-align:center;color:#8B949E">Render not available -- '
            "run Generate to produce images</div>",
            unsafe_allow_html=True,
        )

    st.markdown(zone_pills_html(layout), unsafe_allow_html=True)

    if violations:
        st.markdown(
            f'<span style="color:#E53E3E">❌ {len(violations)} violation(s)</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<span style="color:#38A169">✅ No violations</span>', unsafe_allow_html=True)

    if rationale:
        for entry in rationale[:2]:
            rid = entry.get("rule_id", "")
            text = entry.get("text", "")
            st.markdown(
                f'<span style="background:#00D4B1;color:#0D1117;padding:1px 7px;'
                f'border-radius:8px;font-size:0.75rem">{rid}</span>'
                f'<span style="color:#8B949E;font-size:0.9rem;margin-left:6px">{text}</span>',
                unsafe_allow_html=True,
            )

    if st.button("🔄 Interactive 3D", key=f"3d_{v_id}_{index}"):
        env = _get(v, "environment") or {}
        html = _build_threejs_html(v_id, family, layout, env)
        components.html(html, height=650, scrolling=False)

    st.markdown("<hr style='border-color:#30363D;margin:8px 0'>", unsafe_allow_html=True)
