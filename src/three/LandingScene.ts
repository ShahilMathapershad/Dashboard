/**
 * LandingScene — Minimal, Apple-inspired 3D background.
 *
 * Two animated noise-displaced wireframe planes + a sparse star field.
 * No additive blending, no bright particles. Dark, atmospheric, subtle.
 * Inspired by Apple's Pro Display XDR and macOS Sonoma wallpapers.
 */

import * as THREE from 'three';
import { simplex3 } from './noise';

/* ── Constants ────────────────────────────────────────────── */
const MESH_SEGMENTS  = 48;
const MESH_SIZE      = 14;
const NOISE_SCALE    = 0.28;
const NOISE_HEIGHT   = 0.55;
const NOISE_SPEED    = 0.06;
const STAR_COUNT     = 120;
const MOUSE_EASE     = 0.03;
const MOUSE_AMP      = 0.4;

/* ── Colors (kept dark — never let white accumulate) ─────── */
const ACCENT_BLUE   = 0x3a6cb5;   // muted blue  — darker than UI accent
const ACCENT_PURPLE = 0x5a2ea0;   // muted purple
const STAR_COLOR    = 0x8899cc;   // desaturated blue-white

export class LandingScene {
  private container: HTMLElement;
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;
  private renderer: THREE.WebGLRenderer;
  private meshFront!: THREE.Mesh;
  private meshBack!: THREE.Mesh;
  private stars!: THREE.Points;
  private clock: THREE.Clock;
  private mouse = { x: 0, y: 0, tx: 0, ty: 0 };
  private raf = 0;
  private disposed = false;

  constructor(container: HTMLElement) {
    this.container = container;
    this.clock = new THREE.Clock();

    /* ── Renderer ── */
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'low-power',
    });
    const { width, height } = container.getBoundingClientRect();
    this.renderer.setSize(width || window.innerWidth, height || window.innerHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    this.renderer.setClearColor(0x000000, 0);  // fully transparent — page bg shows through
    container.appendChild(this.renderer.domElement);
    // Fade in after first render
    this.renderer.domElement.style.opacity = '0';
    this.renderer.domElement.style.transition = 'opacity 1.2s cubic-bezier(0.16, 1, 0.3, 1)';

    /* ── Scene / Camera ── */
    this.scene = new THREE.Scene();
    const aspect = (width || window.innerWidth) / (height || window.innerHeight);
    this.camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 100);
    this.camera.position.set(0, 3.5, 10);
    this.camera.lookAt(0, 0, 0);

    /* ── Build objects ── */
    this.meshFront = this.buildMesh(ACCENT_BLUE, 0.22);
    this.meshBack  = this.buildMesh(ACCENT_PURPLE, 0.10);
    this.meshBack.position.set(0.5, -0.4, -1.8);
    this.meshBack.rotation.z = 0.15;
    this.stars = this.buildStars();

    this.scene.add(this.meshFront, this.meshBack, this.stars);

    /* ── Events ── */
    this.onMouseMove = this.onMouseMove.bind(this);
    this.onResize    = this.onResize.bind(this);
    window.addEventListener('mousemove', this.onMouseMove, { passive: true });
    window.addEventListener('resize',    this.onResize,    { passive: true });

    /* ── Start ── */
    requestAnimationFrame(() => {
      this.renderer.domElement.style.opacity = '1';
    });
    this.animate();
  }

  /* ── Wireframe noise mesh ──────────────────────────────── */
  private buildMesh(hexColor: number, opacity: number): THREE.Mesh {
    const geo = new THREE.PlaneGeometry(MESH_SIZE, MESH_SIZE, MESH_SEGMENTS, MESH_SEGMENTS);
    geo.rotateX(-Math.PI * 0.42);

    const mat = new THREE.MeshBasicMaterial({
      color: hexColor,
      wireframe: true,
      transparent: true,
      opacity,
    });

    return new THREE.Mesh(geo, mat);
  }

  /* ── Sparse star field ─────────────────────────────────── */
  private buildStars(): THREE.Points {
    const positions = new Float32Array(STAR_COUNT * 3);
    for (let i = 0; i < STAR_COUNT; i++) {
      positions[i * 3]     = (Math.random() - 0.5) * 20;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 14;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 6 - 4;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    const mat = new THREE.PointsMaterial({
      color: STAR_COLOR,
      size: 0.05,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.45,
    });
    return new THREE.Points(geo, mat);
  }

  /* ── Animation loop ────────────────────────────────────── */
  private animate = (): void => {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(this.animate);

    const t = this.clock.getElapsedTime();

    /* Smooth mouse */
    this.mouse.x += (this.mouse.tx - this.mouse.x) * MOUSE_EASE;
    this.mouse.y += (this.mouse.ty - this.mouse.y) * MOUSE_EASE;

    /* Displace front mesh vertices */
    this.animateMesh(this.meshFront, t, 0);
    this.animateMesh(this.meshBack,  t, 40); // phase offset for variety

    /* Subtle camera drift */
    this.camera.position.x = this.mouse.x * MOUSE_AMP;
    this.camera.position.y = 3.5 + this.mouse.y * MOUSE_AMP * 0.4;
    this.camera.lookAt(0, 0, 0);

    /* Slow star drift */
    this.stars.rotation.y = t * 0.004;

    this.renderer.render(this.scene, this.camera);
  };

  private animateMesh(mesh: THREE.Mesh, t: number, seed: number): void {
    const pos = mesh.geometry.attributes.position;
    const count = pos.count;
    for (let i = 0; i < count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      const y = simplex3(
        x * NOISE_SCALE + t * NOISE_SPEED + seed,
        z * NOISE_SCALE,
        t * NOISE_SPEED * 0.4 + seed
      ) * NOISE_HEIGHT;
      pos.setY(i, y);
    }
    pos.needsUpdate = true;
  }

  /* ── Events ────────────────────────────────────────────── */
  private onMouseMove(e: MouseEvent): void {
    this.mouse.tx = (e.clientX / window.innerWidth  - 0.5) * 2;
    this.mouse.ty = -(e.clientY / window.innerHeight - 0.5) * 2;
  }

  private onResize(): void {
    const w = window.innerWidth, h = window.innerHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  /* ── Cleanup ───────────────────────────────────────────── */
  destroy(): void {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    window.removeEventListener('mousemove', this.onMouseMove);
    window.removeEventListener('resize', this.onResize);

    this.scene.traverse((obj) => {
      if ('geometry' in obj) (obj as THREE.Mesh).geometry?.dispose();
      if ('material' in obj) {
        const m = (obj as THREE.Mesh).material;
        if (Array.isArray(m)) m.forEach(x => x.dispose()); else m?.dispose();
      }
    });

    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
