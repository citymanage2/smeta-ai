let ctx: AudioContext | null = null;

document.addEventListener('click', () => {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === 'suspended') ctx.resume();
}, { once: false });

function playTone(freq: number, duration: number, startTime: number, gain = 0.3): void {
  if (!ctx) return;
  const osc = ctx.createOscillator();
  const gainNode = ctx.createGain();
  osc.connect(gainNode);
  gainNode.connect(ctx.destination);
  osc.type = 'sine';
  osc.frequency.setValueAtTime(freq, startTime);
  gainNode.gain.setValueAtTime(gain, startTime);
  gainNode.gain.exponentialRampToValueAtTime(0.001, startTime + duration);
  osc.start(startTime);
  osc.stop(startTime + duration);
}

export function playSuccess(): void {
  if (!ctx) return;
  const now = ctx.currentTime;
  playTone(523.25, 0.08, now);       // C5
  playTone(659.25, 0.15, now + 0.1); // E5
}

export function playError(): void {
  if (!ctx) return;
  const now = ctx.currentTime;
  playTone(246.94, 0.4, now, 0.25); // B3
}
