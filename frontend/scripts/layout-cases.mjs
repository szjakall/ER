// 第四轮布局回归 / 截图共用的 6 组测试图
export const cases = [
  {
    id: "c1-one-entity",
    name: "一个实体 + 五个属性",
    diagram: {
      elements: [
        {
          id: "rect_001",
          shape: "rectangle",
          label: "学生",
          attributes: ["*学号", "姓名", "性别", "年龄", "学院"],
          position: { x: 260, y: 250 },
        },
      ],
      connections: [],
    },
  },
  {
    id: "c2-two-entities",
    name: "两个实体 + 一个联系",
    diagram: {
      elements: [
        {
          id: "rect_001",
          shape: "rectangle",
          label: "学生",
          attributes: ["*学号", "姓名", "性别"],
          position: { x: 200, y: 260 },
        },
        {
          id: "rect_002",
          shape: "rectangle",
          label: "课程",
          attributes: ["*课程号", "课程名", "学分"],
          position: { x: 780, y: 260 },
        },
        {
          id: "dia_001",
          shape: "diamond",
          label: "选修",
          attributes: ["成绩"],
          position: { x: 490, y: 260 },
        },
      ],
      connections: [
        { id: "conn_001", from: "rect_001", to: "dia_001", type: "diamond_line", label: "", cardinality: "M" },
        { id: "conn_002", from: "dia_001", to: "rect_002", type: "diamond_line", label: "", cardinality: "N" },
      ],
    },
  },
  {
    id: "c3-three-entities",
    name: "三个实体 + 多个联系",
    diagram: {
      elements: [
        { id: "rect_001", shape: "rectangle", label: "学生", attributes: ["*学号", "姓名"], position: { x: 180, y: 180 } },
        { id: "rect_002", shape: "rectangle", label: "课程", attributes: ["*课程号", "课程名"], position: { x: 760, y: 180 } },
        { id: "rect_003", shape: "rectangle", label: "教师", attributes: ["*工号", "姓名"], position: { x: 470, y: 520 } },
        { id: "dia_001", shape: "diamond", label: "选修", attributes: ["成绩"], position: { x: 470, y: 180 } },
        { id: "dia_002", shape: "diamond", label: "讲授", attributes: [], position: { x: 620, y: 350 } },
        { id: "dia_003", shape: "diamond", label: "指导", attributes: [], position: { x: 320, y: 350 } },
      ],
      connections: [
        { id: "conn_001", from: "rect_001", to: "dia_001", type: "diamond_line", label: "", cardinality: "M" },
        { id: "conn_002", from: "dia_001", to: "rect_002", type: "diamond_line", label: "", cardinality: "N" },
        { id: "conn_003", from: "rect_002", to: "dia_002", type: "diamond_line", label: "", cardinality: "1" },
        { id: "conn_004", from: "dia_002", to: "rect_003", type: "diamond_line", label: "", cardinality: "N" },
        { id: "conn_005", from: "rect_001", to: "dia_003", type: "diamond_line", label: "", cardinality: "1" },
        { id: "conn_006", from: "dia_003", to: "rect_003", type: "diamond_line", label: "", cardinality: "N" },
      ],
    },
  },
  {
    id: "c4-complex",
    name: "大量属性的复杂 ER 图",
    diagram: {
      elements: [
        {
          id: "rect_001",
          shape: "rectangle",
          label: "客户",
          attributes: ["*客户编号", "客户名称", "联系电话", "电子邮箱", "注册日期", "客户等级", "所在城市", "详细地址"],
          position: { x: 160, y: 160 },
        },
        {
          id: "rect_002",
          shape: "rectangle",
          label: "订单",
          attributes: ["*订单编号", "下单时间", "订单金额", "订单状态", "付款方式", "备注信息"],
          position: { x: 600, y: 160 },
        },
        {
          id: "rect_003",
          shape: "rectangle",
          label: "商品",
          attributes: ["*商品编号", "商品名称", "规格型号", "单价", "库存数量", "上架状态"],
          position: { x: 1080, y: 160 },
        },
        {
          id: "rect_004",
          shape: "rectangle",
          label: "仓库",
          attributes: ["*仓库编号", "仓库名称", "所在区域", "负责人", "容量"],
          position: { x: 600, y: 620 },
        },
        {
          id: "rect_005",
          shape: "rectangle",
          label: "供应商",
          attributes: ["*供应商编号", "供应商名称", "联系人", "电话", "地址"],
          position: { x: 1080, y: 620 },
        },
        { id: "dia_001", shape: "diamond", label: "下单", attributes: [], position: { x: 380, y: 160 } },
        { id: "dia_002", shape: "diamond", label: "包含", attributes: ["数量"], position: { x: 840, y: 160 } },
        { id: "dia_003", shape: "diamond", label: "存放", attributes: [], position: { x: 600, y: 380 } },
        { id: "dia_004", shape: "diamond", label: "供应", attributes: ["供货价"], position: { x: 840, y: 620 } },
        { id: "ell_001", shape: "ellipse", label: "会员属性", attributes: [], position: { x: 300, y: 720 } },
      ],
      connections: [
        { id: "conn_001", from: "rect_001", to: "dia_001", type: "diamond_line", label: "", cardinality: "1" },
        { id: "conn_002", from: "dia_001", to: "rect_002", type: "diamond_line", label: "", cardinality: "N" },
        { id: "conn_003", from: "rect_002", to: "dia_002", type: "diamond_line", label: "", cardinality: "1" },
        { id: "conn_004", from: "dia_002", to: "rect_003", type: "diamond_line", label: "", cardinality: "N" },
        { id: "conn_005", from: "rect_003", to: "dia_003", type: "diamond_line", label: "", cardinality: "N" },
        { id: "conn_006", from: "dia_003", to: "rect_004", type: "diamond_line", label: "", cardinality: "1" },
        { id: "conn_007", from: "rect_004", to: "dia_004", type: "diamond_line", label: "", cardinality: "N" },
        { id: "conn_008", from: "dia_004", to: "rect_005", type: "diamond_line", label: "", cardinality: "1" },
      ],
    },
  },
  {
    id: "c5-weak-multi",
    name: "弱实体 + 多值属性",
    diagram: {
      elements: [
        {
          id: "rect_001",
          shape: "rectangle",
          label: "职工",
          attributes: ["*职工编号", "姓名", "性别", "出生年月", "家庭住址", "联系电话"],
          position: { x: 240, y: 240 },
        },
        {
          id: "rect_002",
          shape: "rectangle",
          label: "亲属",
          is_weak: true,
          attributes: ["#称呼", "姓名", "年龄", "政治面貌", "工作单位"],
          position: { x: 760, y: 240 },
        },
        { id: "dia_001", shape: "diamond", label: "具有", is_identifying: true, attributes: [], position: { x: 500, y: 240 } },
        {
          id: "rect_003",
          shape: "rectangle",
          label: "员工",
          attributes: ["*员工号", "姓名", "技能", "电话", "邮箱", "职级"],
          attr_style: { "2": "multi", "5": "derived" },
          position: { x: 500, y: 560 },
        },
      ],
      connections: [
        { id: "conn_001", from: "rect_001", to: "dia_001", type: "diamond_line", label: "", cardinality: "1" },
        { id: "conn_002", from: "dia_001", to: "rect_002", type: "diamond_line", label: "", cardinality: "N" },
      ],
    },
  },
  {
    id: "c6-mixed-names",
    name: "中英文混合的长属性名称",
    diagram: {
      elements: [
        {
          id: "rect_001",
          shape: "rectangle",
          label: "读者Reader",
          attributes: [
            "*读者ID",
            "longEnglishAttributeName",
            "中英文Mixed属性Name",
            "超长属性名称测试用例",
            "联系方式ContactInfo",
            "registrationTimestamp",
          ],
          position: { x: 300, y: 260 },
        },
        {
          id: "rect_002",
          shape: "rectangle",
          label: "图书Book",
          attributes: ["*图书ID", "国际标准书号ISBN", "书名Title", "出版社Publisher", "价格Price"],
          position: { x: 820, y: 260 },
        },
        { id: "dia_001", shape: "diamond", label: "借阅Borrow", attributes: ["借阅日期BorrowDate"], position: { x: 560, y: 260 } },
      ],
      connections: [
        { id: "conn_001", from: "rect_001", to: "dia_001", type: "diamond_line", label: "", cardinality: "M" },
        { id: "conn_002", from: "dia_001", to: "rect_002", type: "diamond_line", label: "", cardinality: "N" },
      ],
    },
  },
];


