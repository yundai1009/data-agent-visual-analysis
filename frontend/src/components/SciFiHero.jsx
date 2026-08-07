// 登录页科幻 3D 场景（Three.js / React Three Fiber）
// 360° 鼠标环绕跟随 + 行星式发光核心 + 圆形数据球体环绕 + 双层宇宙繁星
import { Suspense, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float, Sparkles, Stars } from '@react-three/drei';
import * as THREE from 'three';

// 主体：行星式发光核心（中央发光核 + 玻璃壳 + 光环 + 环绕圆形数据球）
function PlanetCore() {
  const group = useRef(null);
  const orbiters = useRef([]);
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (group.current) group.current.rotation.y = t * 0.1;
    // 圆形数据球绕中央核公转
    orbiters.current.forEach((o, i) => {
      if (o) {
        const a = t * (0.5 + i * 0.14) + i * (Math.PI * 2 / orbiters.current.length);
        const rad = o.userData.rad;
        const tilt = o.userData.tilt;
        o.position.set(
          Math.cos(a) * rad * Math.cos(tilt),
          Math.sin(a) * rad * Math.sin(tilt),
          Math.sin(a) * rad * Math.cos(tilt),
        );
      }
    });
  });

  // 环绕圆形数据球（轨道半径、大小、颜色、倾角）
  const orbs = [
    { rad: 1.85, size: 0.16, tilt: 0.35, color: '#7fb3e8', ei: 1.6 },
    { rad: 2.2, size: 0.12, tilt: -0.5, color: '#8fc3ee', ei: 1.4 },
    { rad: 1.55, size: 0.2, tilt: 0.9, color: '#4a8ac2', ei: 1.8 },
    { rad: 2.45, size: 0.1, tilt: -0.2, color: '#9cc4e8', ei: 1.3 },
    { rad: 1.75, size: 0.14, tilt: 1.5, color: '#b9d8f2', ei: 1.5 },
    { rad: 2.6, size: 0.11, tilt: 0.6, color: '#8fc3ee', ei: 1.2 },
  ];

  return (
    <group ref={group}>
      {/* 中央发光核 */}
      <Float speed={1.3} rotationIntensity={0.2} floatIntensity={0.5}>
        {/* 外玻璃壳 */}
        <mesh scale={1.35}>
          <sphereGeometry args={[1, 48, 48]} />
          <meshPhysicalMaterial color="#3d7bb8" emissive="#0f4c81" emissiveIntensity={0.35} roughness={0.05} metalness={0.2} transmission={0.75} thickness={1.5} ior={1.4} transparent opacity={0.55} />
        </mesh>
        {/* 内发光核 */}
        <mesh scale={0.95}>
          <sphereGeometry args={[1, 48, 48]} />
          <meshStandardMaterial color="#a8d4f5" emissive="#7fb3e8" emissiveIntensity={2.2} transparent opacity={0.95} />
        </mesh>
        {/* 极细线框（不扭曲，仅轮廓感） */}
        <mesh scale={1.02}>
          <sphereGeometry args={[1, 32, 32]} />
          <meshBasicMaterial color="#8fc3ee" wireframe transparent opacity={0.08} />
        </mesh>
      </Float>

      {/* 光环（环绕中央核，非主体） */}
      <mesh rotation={[Math.PI / 2.3, 0.4, 0]}>
        <torusGeometry args={[1.62, 0.012, 16, 180]} />
        <meshStandardMaterial color="#7fb3e8" emissive="#2e7ab8" emissiveIntensity={1.6} transparent opacity={0.7} />
      </mesh>
      <mesh rotation={[Math.PI / 2.7, -0.5, 0]}>
        <torusGeometry args={[1.92, 0.009, 16, 180]} />
        <meshStandardMaterial color="#8fc3ee" emissive="#4a8ac2" emissiveIntensity={1.2} transparent opacity={0.5} />
      </mesh>

      {/* 圆形数据球（公转环绕） */}
      {orbs.map((o, i) => (
        <mesh
          key={i}
          ref={(el) => { orbiters.current[i] = el; }}
          userData={{ rad: o.rad, tilt: o.tilt }}
        >
          <sphereGeometry args={[o.size, 24, 24]} />
          <meshStandardMaterial color={o.color} emissive={o.color} emissiveIntensity={o.ei} metalness={0.5} roughness={0.15} />
        </mesh>
      ))}
    </group>
  );
}

// 360° 鼠标环绕跟随：横向移动 → 方位角近一圈；纵向 → 俯仰；idle 自动缓转
function Rig() {
  const az = useRef(0);
  const pol = useRef(Math.PI / 2);
  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    const px = state.pointer.x;
    const py = state.pointer.y;
    const ease = 1 - Math.pow(0.002, delta);
    // 目标：鼠标横向 → ±0.95π（接近全角度环绕）；纵向 → 俯仰（限制 35°~145°）
    const targetAz = px * Math.PI * 0.95 + Math.sin(t * 0.1) * 0.15;
    const targetPol = THREE.MathUtils.clamp(Math.PI / 2 - py * 0.6, 0.62, Math.PI - 0.62);
    az.current += (targetAz - az.current) * ease;
    pol.current += (targetPol - pol.current) * ease;
    const r = 4.3;
    state.camera.position.set(
      Math.sin(az.current) * Math.cos(pol.current) * r,
      Math.sin(pol.current) * r,
      Math.cos(az.current) * Math.cos(pol.current) * r,
    );
    state.camera.lookAt(0, 0, 0);
  });
  return null;
}

export default function SciFiHero() {
  return (
    <Canvas
      camera={{ position: [0, 0.1, 4.3], fov: 45 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      style={{ background: 'transparent' }}
    >
      <ambientLight intensity={0.5} />
      <pointLight position={[4, 3, 4]} intensity={100} color="#8fc3ee" />
      <pointLight position={[-4, -2, 3]} intensity={60} color="#0f4c81" />
      <Suspense fallback={null}>
        <PlanetCore />
        {/* 宇宙繁星：近亮层 + 远疏层 */}
        <Stars radius={120} depth={80} count={5200} factor={3.6} saturation={0} fade speed={0.6} />
        <Stars radius={40} depth={30} count={800} factor={5} saturation={0.1} fade speed={0.9} />
        <Sparkles count={220} scale={9} size={3} speed={0.3} color="#9cc4e8" opacity={0.85} />
        <Sparkles count={80} scale={4} size={1.5} speed={0.5} color="#ffffff" opacity={0.9} />
      </Suspense>
      <Rig />
    </Canvas>
  );
}
