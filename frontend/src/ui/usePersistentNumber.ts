import { ref } from "vue";

export function clampNumber(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}

export function readStoredNumber(key: string, fallback: number) {
  try {
    const raw = localStorage.getItem(key);
    const v = Number(raw);
    return Number.isFinite(v) && v > 0 ? v : fallback;
  } catch {
    return fallback;
  }
}

/** 面板尺寸：内存响应式 + localStorage 持久化 */
export function usePersistentNumber(key: string, fallback: number) {
  const value = ref(readStoredNumber(key, fallback));
  function set(v: number) {
    const next = Math.round(v);
    value.value = next;
    try {
      localStorage.setItem(key, String(next));
    } catch {
      /* 隐私模式下忽略 */
    }
  }
  return { value, set };
}
