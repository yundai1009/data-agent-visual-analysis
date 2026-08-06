// 登录页科幻 3D 场景（Three.js / React Three Fiber）
// 中央发光流动球体 + 双轨道光环 + 粒子星云 + 漂浮数据立方体 + 鼠标跟随
import { Suspense, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float, MeshDistortMaterial, Sparkles, Stars } from '@react-three/drei';

function Orb() {
  return (
    <Float speed={1.8} rotationIntensity={0.5} floatIntensity={0.9}>
      <mesh>
        <sphereGeometry args={[1.15, 64, 64]} />
        <MeshDistortMaterial
          color="#2e7ab8"
          emissive="#0f4c81"
          emissiveIntensity={0.5}
          roughness={0.15}
          metalness={0.5}
          distort={0.38}
          speed={2.2}
        />
      </mesh>
      {/* 内层发光核 */}
      <mesh scale={0.55}>
        <sphereGeometry args={[1, 32, 32]} />
        <meshStandardMaterial color="#8fc3ee" emissive="#7fb3e8" emissiveIntensity={2.4} transparent opacity={0.9} />
      </mesh>
    </Float>
  );
}

function Rings() {
  const ring1 = useRef(null);
  const ring2 = useRef(null);
  const ring3 = useRef(null);
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (ring1.current) { ring1.current.rotation.z = t * 0.28; ring1.current.rotation.x = Math.PI / 2.35 + Math.sin(t * 0.2) * 0.12; }
    if (ring2.current) { ring2.current.rotation.z = -t * 0.2; ring2.current.rotation.x = Math.PI / 2.9 + Math.cos(t * 0.16) * 0.1; }
    if (ring3.current) { ring3.current.rotation.z = t * 0.14; ring3.current.rotation.x = Math.PI / 2.1 + Math.sin(t * 0.24 + 1) * 0.08; }
  });
  return (
    <>
      <mesh ref={ring1}>
        <torusGeometry args={[1.75, 0.014, 16, 160]} />
        <meshStandardMaterial color="#7fb3e8" emissive="#2e7ab8" emissiveIntensity={1.6} transparent opacity={0.75} />
      </mesh>
      <mesh ref={ring2}>
        <torusGeometry args={[2.05, 0.01, 16, 160]} />
        <meshStandardMaterial color="#8fc3ee" emissive="#4a8ac2" emissiveIntensity={1.2} transparent opacity={0.5} />
      </mesh>
      <mesh ref={ring3}>
        <torusGeometry args={[2.38, 0.008, 16, 160]} />
        <meshStandardMaterial color="#b9d8f2" emissive="#7fb3e8" emissiveIntensity={0.8} transparent opacity={0.35} />
      </mesh>
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
            <meshStandardMaterial color={c.color} emissive={c.color} emissiveIntensity={1.4} metalness={0.6} roughness={0.2} transparent opacity={0.9} />
          </mesh>
        </Float>
      ))}
    </group>
  );
}

// 鼠标跟随 + 场景微旋
function Rig() {
  useFrame((state, delta) => {
    state.camera.position.x += (state.pointer.x * 0.55 - state.camera.position.x) * delta * 1.6;
    state.camera.position.y += (state.pointer.y * 0.35 + 0.15 - state.camera.position.y) * delta * 1.6;
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
      <ambientLight intensity={0.55} />
      <pointLight position={[4, 3, 4]} intensity={90} color="#8fc3ee" />
      <pointLight position={[-4, -2, 3]} intensity={60} color="#0f4c81" />
      <pointLight position={[0, -3, -2]} intensity={35} color="#2e7ab8" />
      <Suspense fallback={null}>
        <Orb />
        <Rings />
        <DataCubes />
        <Stars radius={70} depth={50} count={2600} factor={3.2} saturation={0} fade speed={0.9} />
        <Sparkles count={140} scale={7} size={2.6} speed={0.35} color="#8fc3ee" opacity={0.8} />
      </Suspense>
      <Rig />
    </Canvas>
  );
}
