import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

// Custom type sizes and text colors must coexist when class lists are merged.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["display-xl", "display-l", "display-m", "h2", "h3", "body", "body-s", "caption", "eyebrow", "data-xxl", "data-xl", "data-l", "data-m", "micro", "tag"] }],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 导航高亮：根路径精确匹配；其余按路径段边界。 */
export function isNavPathActive(pathname: string, path: string): boolean {
  if (path === '/') return pathname === '/'
  return pathname === path || pathname.startsWith(`${path}/`)
}
