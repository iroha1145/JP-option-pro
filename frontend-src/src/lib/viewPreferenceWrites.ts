type PreferenceWriter<T> = (signal?: AbortSignal) => Promise<T>;

export class PreferenceWriteCancelledError extends Error {
  constructor(message = 'preference write cancelled') {
    super(message);
    this.name = 'PreferenceWriteCancelledError';
  }
}

let writeGeneration = 0;
let boundPrincipal: string | undefined;
let writeTail: Promise<unknown> = Promise.resolve();
const inFlightControllers = new Set<AbortController>();

export function currentPreferenceWriteGeneration(): number {
  return writeGeneration;
}

export function bindPreferenceWritePrincipal(principal: string): void {
  boundPrincipal = principal;
}

export function invalidatePreferenceWriteQueue(): void {
  writeGeneration += 1;
  for (const controller of inFlightControllers) {
    controller.abort();
  }
  inFlightControllers.clear();
  writeTail = Promise.resolve();
}

export function resetPreferenceWriteQueue(): void {
  invalidatePreferenceWriteQueue();
  boundPrincipal = undefined;
}

function writeIsCurrent(principal: string | undefined, generation: number): boolean {
  if (generation !== writeGeneration) return false;
  if (principal !== undefined && boundPrincipal !== undefined && principal !== boundPrincipal) {
    return false;
  }
  return true;
}

export function enqueuePreferenceWrite<T>(
  write: PreferenceWriter<T>,
  bind?: { principal?: string | null; generation?: number },
): Promise<T> {
  const capturedPrincipal = bind?.principal === undefined ? undefined : (bind.principal ?? undefined);
  const capturedGeneration = bind?.generation ?? writeGeneration;
  const controller = new AbortController();
  inFlightControllers.add(controller);
  const dispatch = async () => {
    if (!writeIsCurrent(capturedPrincipal, capturedGeneration)) {
      throw new PreferenceWriteCancelledError();
    }
    return write(controller.signal);
  };
  const run = writeTail.then(dispatch, dispatch);
  writeTail = run.then(() => undefined, () => undefined);
  void run.finally(() => {
    inFlightControllers.delete(controller);
  }).catch(() => undefined);
  return run;
}

export async function persistRemoteOrKeepLocal<T extends object>(
  local: T,
  write: PreferenceWriter<T>,
  bind?: { principal?: string | null; generation?: number },
): Promise<T & { persisted?: boolean; syncError?: unknown }> {
  try {
    const saved = await enqueuePreferenceWrite(write, bind);
    return { ...saved, persisted: true };
  } catch (error) {
    return { ...local, persisted: false, syncError: error };
  }
}
