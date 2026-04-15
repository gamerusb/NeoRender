import type { LucideProps } from "lucide-react";

/**
 * Общие параметры Lucide для чёткого рендера в UI (единый вес линии по размеру).
 * strokeWidth слегка выше дефолта Lucide (2 @24px), чтобы на 14–18px иконки читались чётче.
 */
export function navIconProps(): Pick<LucideProps, "size" | "strokeWidth" | "absoluteStrokeWidth"> {
  return { size: 18, strokeWidth: 1.75, absoluteStrokeWidth: true };
}

export function uiIconProps(size: 13 | 14 | 15 | 16 | 18 | 20 = 16): Pick<LucideProps, "size" | "strokeWidth" | "absoluteStrokeWidth"> {
  const sw = size <= 13 ? 2 : size <= 14 ? 2 : size <= 16 ? 1.85 : 1.75;
  return { size, strokeWidth: sw, absoluteStrokeWidth: true };
}
