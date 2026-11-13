/**
 * 画布设计层：ER 图的所有渲染常量只在这里定义。
 * 外壳（工具栏、面板）走 tokens.css；画布永远是教材式的黑白陈氏记法。
 */

/** 墨色：图形描边、文字、连线 */
export const INK = "#1C1A16";
/** 纸白：所有图形填充、页面填充 */
export const PAPER = "#FFFFFF";
/** 桌面：页面之外的底色 */
export const DESK = "#EFECE4";
/** 页面边框（很淡，只用来分隔纸与桌） */
export const PAGE_BORDER = "rgba(28, 26, 22, 0.16)";
/** 辅助网格点 */
export const GRID_DOT = "rgba(28, 26, 22, 0.12)";
export const GRID_STEP = 20;
/** 拖动吸附步长（px） */
export const SNAP_STEP = 8;

/** 选中 / 悬停：只出现在图形外部 */
export const SEL = "#4F46E5";
export const SEL_SOFT = "rgba(79, 70, 229, 0.10)";

/** 严重度外环（永远不改变图形本身的填充与描边） */
export const HALO: Record<"error" | "warn", string> = {
  error: "rgba(201, 33, 71, 0.55)",
  warn: "rgba(194, 65, 12, 0.50)",
};
export const HALO_LINE: Record<"error" | "warn", string> = {
  error: "rgba(201, 33, 71, 0.14)",
  warn: "rgba(194, 65, 12, 0.14)",
};

/**
 * 整体排版缩放（内容级，不是屏幕级）。
 * 图形尺寸、字号、描边、端点都乘同一个 S；viewportTransform 只负责把页面装进屏幕。
 * min 由「基数 13px × S ≥ 12px」反推：不允许为了塞进页面把正文压到不可读。
 */
export const SCALE = {
  min: 0.93,
  max: 2.6,
  /** 新建元素默认继承的缩放 */
  default: 1,
} as const;

/** 画布字级 */
export const FONT = {
  family: '"Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", sans-serif',
  entity: 15,
  relation: 14,
  attr: 14,
  card: 13,
} as const;

export const WEIGHT = {
  entity: 600,
  relation: 600,
  attr: 400,
  card: 600,
} as const;

/** 线宽：世界坐标宽度。可见描边随视口缩放，与文字 / 图形保持同一屏幕比例；
 *  只有命中线、选择框、严重度外环使用 strokeUniform 固定在屏幕上。 */
export const STROKE = {
  shape: 1.5,
  inner: 1.2,
  link: 1.25,
  halo: 2.5,
  underline: 1.2,
} as const;

/** 图形几何（px，画布坐标） */
export const GEO = {
  entityH: 46,
  entityPadX: 22,
  entityPadY: 11,
  entityMinW: 84,
  entityMaxW: 320,

  attrH: 34,
  attrPadX: 20,
  attrPadY: 9,
  attrMinW: 68,
  attrMaxW: 300,
  /** 单行文字超过它就开始换行，避免椭圆无限变宽 */
  attrMaxTextW: 236,

  diamondH: 56,
  diamondPadX: 34,
  diamondPadY: 12,
  diamondMinW: 104,
  diamondMaxW: 340,
  /** 菱形内部可用宽度比外接矩形窄 */
  diamondMaxTextW: 210,

  /** 弱实体 / 双椭圆 / 标识联系的内缩 */
  inset: 4,

  /** 属性椭圆与图形的间隙 */
  attrGap: 14,
  /** 相邻属性椭圆的最小空隙 */
  attrPad: 10,

  /** 基数：距实体端点的距离、法向偏移 */
  cardFromEnd: 26,
  cardOffset: 12,
} as const;
