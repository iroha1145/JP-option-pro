/**
 * One-dimensional sheet physics, adapted from Feel's magnets, wall and Body
 * (diip3sh/feel @ c9b22fa, MIT; see THIRD_PARTY_NOTICES.md).
 *
 * A released sheet has no spring target. It coasts through a field with two
 * resting places: fully open and fully closed. Content stays at its full height.
 */
const TAU = 2 * Math.PI;
const STEP = 1 / 240;
const MASS = 1;
const DAMPING = 2 * 0.8 * MASS * TAU * 2.2;
const FAR_K = MASS * (TAU * 1.1) ** 2;
const NEAR_K = MASS * (TAU * 7) ** 2;
const WALL_K = MASS * (TAU * 8) ** 2;
const WALL_C = 2 * 0.9 * Math.sqrt(WALL_K * MASS);
const HAND_K = (TAU * 6) ** 2;
const HAND_C = 2 * Math.sqrt(HAND_K * MASS);

export interface SheetSample { x: number; v: number }
export interface SheetPath { samples: SheetSample[]; duration: number; rest: number }

export class MagneticSheetBody {
  height: number;
  x: number;
  v: number;
  hand: SheetSample | null = null;

  constructor(height: number, x = 0, v = 0) {
    this.height = Math.max(1, height);
    this.x = x;
    this.v = v;
  }

  rest(x = this.x): number {
    return x > this.height / 2 ? this.height : 0;
  }

  projected(): number {
    return this.x + this.v * MASS / DAMPING;
  }

  force(x: number, v: number): number {
    const distance = x - this.rest(x);
    const near = Math.max(0, 1 - Math.abs(distance) / 22);
    let force = -DAMPING * v - FAR_K * distance
      - NEAR_K * distance * near * near * (3 - 2 * near);
    if (x < 0) force += -WALL_K * x - (v < 0 ? WALL_C * v : 0);
    if (x > this.height) force += -WALL_K * (x - this.height) - (v > 0 ? WALL_C * v : 0);
    if (this.hand) force += HAND_K * (this.hand.x - x) + HAND_C * (this.hand.v - v);
    return force;
  }

  step(dt: number): void {
    let remaining = Math.max(0, Math.min(dt, 0.05));
    while (remaining > 1e-7) {
      const h = Math.min(remaining, STEP);
      const { x, v } = this;
      const a1 = this.force(x, v) / MASS;
      const v2 = v + h * a1 / 2;
      const a2 = this.force(x + h * v / 2, v2) / MASS;
      const v3 = v + h * a2 / 2;
      const a3 = this.force(x + h * v2 / 2, v3) / MASS;
      const v4 = v + h * a3;
      const a4 = this.force(x + h * v3, v4) / MASS;
      this.x += h * (v + 2 * v2 + 2 * v3 + v4) / 6;
      this.v += h * (a1 + 2 * a2 + 2 * a3 + a4) / 6;
      remaining -= h;
    }
  }

  settled(): boolean {
    return !this.hand && Math.abs(this.x - this.rest()) < 0.25 && Math.abs(this.v) < 4;
  }

  /** Used by both browser keyframes and tests; duration follows the trajectory. */
  path(): SheetPath {
    const ghost = new MagneticSheetBody(this.height, this.x, this.v);
    const samples = [{ x: ghost.x, v: ghost.v }];
    // A numerical safety bound, not an animation duration. Normal paths stop
    // as soon as the same physical resting tolerances are reached.
    for (let frame = 0; frame < 1440 && !ghost.settled(); frame++) {
      ghost.step(1 / 120);
      samples.push({ x: ghost.x, v: ghost.v });
    }
    const rest = ghost.rest();
    samples.push({ x: rest, v: 0 });
    return { samples, rest, duration: (samples.length - 1) * 1000 / 120 };
  }

  /** A keyboard command is an impulse that the same field catches at a stop. */
  kickTo(stop: number): void {
    this.hand = null;
    if (Math.abs(this.x - stop) < 0.25 && Math.abs(this.v) < 4) {
      this.x = stop;
      this.v = 0;
      return;
    }
    const direction = Math.sign(stop - this.x) || 1;
    for (let speed = 40; speed < 40_000; speed *= 1.18) {
      const ghost = new MagneticSheetBody(this.height, this.x, direction * speed);
      if (ghost.path().rest === stop) {
        // Cross the field decisively instead of barely clearing its midpoint.
        // When already inside the destination's basin, the first passing speed
        // can be tiny: give the command enough coast to cover most of the
        // remaining distance as well. The magnets finish the final approach.
        // Real drag release never calls kickTo or receives this impulse.
        const coastSpeed = Math.abs(stop - this.x) * DAMPING / MASS;
        this.v = direction * Math.max(speed * 1.5, coastSpeed * 0.95);
        return;
      }
    }
    this.v = (stop - this.x) * DAMPING / MASS;
  }
}
