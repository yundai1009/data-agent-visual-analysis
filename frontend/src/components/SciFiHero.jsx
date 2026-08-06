// 登录页科幻 3D 场景（Three.js / React Three Fiber）
// 干净发光玻璃球体 + 双轨道光环 + 宇宙繁星星云 + 数据立方体 + 强沉浸鼠标跟随
import { Suspense, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float, Sparkles, Stars } from '@react-three/drei';
import * as THREE from 'three';

function Orb() {
  const group = useRef(null);
  useFrame((state, delta) => {
    if (group.current) group.current.rotation.y += delta * 0.18;
  });
  return (
    <Float speed={1.4} rotationIntensity={0.25} floatIntensity={0.6}>
      <group ref={group}>
        {/* 干净发光球体（不发散扭曲） */}
        <mesh>
          <sphereGeometry args={[1.15, 64, 64]} />
          <meshPhysicalMaterial
            color="#2e7ab8"
            emissive="#0f4c81"
            emissiveIntensity={0.55}
            roughness={0.08}
            metalness={0.35}
            clearcoat={0.9}
            clearcoatRoughness={0.12}
            transmission={0.5}
            thickness={1.2}
            ior={1.45}
          />
        </mesh>
        {/* 内层发光核 */}
        <mesh scale={0.5}>
          <sphereGeometry args={[1, 48, 48]} />
          <meshStandardMaterial color="#a8d4f5" emissive="#7fb3e8" emissiveIntensity={2.6} transparent opacity={0.95} />
        </mesh>
        {/* 表面流动能量纹（贴图环，不是几何变形） */}
        <mesh scale={1.02}>
          <sphereGeometry args={[1.15, 64, 64]} />
          <meshBasicMaterial color="#8fc3ee" wireframe transparent opacity={0.06} />
        </mesh>
      </group>
    </Float>
  );
}

function Rings() {
  const ring1 = useRef(null);
  const ring2 = useRef(null);
  const ring3 = useRef(null);
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (ring1.current) { ring1.current.rotation.z = t * 0.3; ring1.current.rotation.x = Math.PI / 2.3 + Math.sin(t * 0.2) * 0.14; }
    if (ring2.current) { ring2.current.rotation.z = -t * 0.22; ring2.current.rotation.x = Math.PI / 2.85 + Math.cos(t * 0.16) * 0.1; }
    if (ring3.current) { ring3.current.rotation.z = t * 0.15; ring3.current.rotation.x = Math.PI / 2.05 + Math.sin(t * 0.24 + 1) * 0.09; }
  });
  return (
    <>
      <mesh ref={ring1}>
        <torusGeometry args={[1.72, 0.016, 16, 160]} />
        <meshStandardMaterial color="#7fb3e8" emissive="#2e7ab8" emissiveIntensity={1.8} transparent opacity={0.8} />
      </mesh>
      <mesh ref={ring2}>
        <torusGeometry args={[2.02, 0.011, 16, 160]} />
        <meshStandardMaterial color="#8fc3ee" emissive="#4a8ac2" emissiveIntensity={1.4} transparent opacity={0.55} />
      </mesh>
      <mesh ref={ring3}>
        <torusGeometry args={[2.36, 0.008, 16, 160]} />
        <meshStandardMaterial color="#b9d8f2" emissive="#7fb3e8" emissiveIntensity={0.9} transparent opacity={0.4} />
      </mesh>
      {/* 环上漂浮发光点 */}
      {[0, 1, 2].map((i) => (
        <mesh key={i} position={[1.72, 0, 0]}>
          <sphereGeometry args={[0.045, 16, 16]} />
          <meshStandardMaterial color="#cfe6f8" emissive="#8fc3ee" emissiveIntensity={4} />
        </mesh>
      ))}
    </>
  );
}

// 环绕数据立方体（3D 图表元素，缓慢公转）
function DataCubes() {
  const group = useRef(null);
  useFrame((state) => {
    if (group.current) group.current.rotation.y = state.clock.elapsedTime * 0.22;
  });
  const cubes = [
    { pos: [2.7, 0.7, 0.3], size: 0.16, speed: 0.55, color: '#7fb3e8' },
    { pos: [-2.6, -0.6, 0.4], size: 0.13, speed: 0.45, color: '#8fc3ee' },
    { pos: [0.4, 2.0, -0.6], size: 0.12, speed: 0.5, color: '#4a8ac2' },
    { pos: [-0.5, -1.9, 0.5], size: 0.15, speed: 0.6, color: '#5b8cb8' },
    { pos: [2.0, -1.4, 0.7], size: 0.1, speed: 0.42, color: '#9cc4e8' },
    { pos: [-2.1, 1.4, -0.4], size: 0.11, speed: 0.48, color: '#8fc3ee' },
  ];
  return (
    <group ref={group}>
      {cubes.map((c, i) => (
        <Float key={i} speed={c.speed} rotationIntensity={1.4} floatIntensity={1.2}>
          <mesh position={c.pos}>
            <boxGeometry args={[c.size, c.size, c.size]} />
            <meshStandardMaterial color={c.color} emissive={c.color} emissiveIntensity={1.5} metalness={0.6} roughness={0.2} transparent opacity={0.9} />
          </mesh>
        </Float>
      ))}
    </group>
  );
}

// 强沉浸鼠标跟随：相机平移更明显、响应更快，并加滚动视差
function Rig() {
  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    const px = state.pointer.x;
    const py = state.pointer.y;
    // 目标位置：鼠标偏移放大 + 缓慢自动漂移（呼吸感）
    const tx = px * 0.95 + Math.sin(t * 0.18) * 0.12;
    const ty = py * 0.6 + 0.12 + Math.cos(t * 0.14) * 0.08;
    const ease = 1 - Math.pow(0.0018, delta); // 平滑缓动
    state.camera.position.x += (tx - state.camera.position.x) * ease;
    state.camera.position.y += (ty - state.camera.position.y) * ease;
    // 轻微 z 呼吸（纵深沉浸）
    state.camera.position.z = 4.4 + Math.sin(t * 0.22) * 0.18;
    state.camera.lookAt(0, 0, 0);
  });
  return null;
}

export default function SciFiHero() {
  return (
    <Canvas
      camera={{ position: [0, 0.1, 4.4], fov: 45 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      style={{ background: 'transparent' }}
    >
      <ambientLight intensity={0.5} />
      <pointLight position={[4, 3, 4]} intensity={110} color="#8fc3ee" />
      <pointLight position={[-4, -2, 3]} intensity={70} color="#0f4c81" />
      <pointLight position={[0, -3, -2]} intensity={40} color="#2e7ab8" />
      <Suspense fallback={null}>
        <Orb />
        <Rings />
        <DataCubes />
        {/* 宇宙繁星：近层（亮、密）+ 远层（弱、疏）营造深度星云 */}
        <Stars radius={120} depth={80} count={5200} factor={3.6} saturation={0} fade speed={0.6} />
        <Stars radius={40} depth={30} count={800} factor={5} saturation={0.1} fade speed={0.9} />
        <Sparkles count={220} scale={9} size={3} speed={0.3} color="#9cc4e8" opacity={0.85} />
        <Sparkles count={80} scale={4} size={1.5} speed={0.5} color="#ffffff" opacity={0.9} />
      </Suspense>
      <Rig />
    </Canvas>
  );
}
