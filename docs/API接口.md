# 一、编辑器API

> 请求编辑器后端服务

- 接口路径相对于编辑器页面地址
- 后端服务为 NodeJS/Express 框架，实现 storage 目录下文件增删改查操作
- 响应 Content-Type: application/json

## 1. 文件列表

```http
GET /explore/{path} HTTP/1.1
```

### 请求参数

- path: 要查询的路径，例如 `displays` 或 `displays/demo` 等

### 响应

- 返回指定目录下的所有子目录/文件列表（JSON字符串，key为文件名或目录名；value为 `true` 时是文件，为对象时是目录）

### 示例

```js
const fileTree = await fetch(
  "http://daoscada.local/hmi-ui/explore/displays",
).then((res) => res.json());

console.log(fileTree);
```

输出：

```jsonc
{ "aaa": { "bbb.json": true } }

// `displays/aaa` 是一个目录
// `displays/aaa/bbb.json` 是一个文件
```

## 2. 文件保存

```http
POST /upload HTTP/1.1
Content-Type: multipart/form-data
```

将文件内容保存到指定路径

- 路径必须带扩展名，否则无法保存成功；
- 父级目录如果不存在会自动创建，无需手动 mkdir；
- 路径上已经存在的文件会被直接覆盖。

### 请求参数

- path: 要上传的路径，**必须带扩展名**，例如 `displays/aaa/bbb.json`
- content: 要上传的文件内容（文本内容、json字符串、或base64编码的二进制数据），例如 `{"v":"8.1.5","p":{},"a":{},"d":[]}`

### 响应

- 无返回数据，Status 200表示上传成功

### 示例：

> 在编辑器界面中保存画面或控件时，会发送2个保存请求，分别保存json文件和其png缩略图。

```js
// 保存json文件
const formData = new FormData();
formData.append("path", `displays/aaa/bbb.json`);
formData.append(
  "content",
  JSON.stringify({
    /* 要上传的json对象 */
  }),
);
await fetch("http://daoscada.local/hmi-ui/upload", {
  method: "POST",
  body: formData,
});
```

```js
// 从canvas获取快照，保存png缩略图
const canvas = document.getElementById(/* 画布id */ "myCanvas");
const base64Image = canvas.toDataURL("image/png"); // 'data:image/png;base64,iVBORw0KGgo......'
const formData = new FormData();
formData.append("path", `displays/aaa/bbb.png`);
formData.append("content", base64Image);
await fetch("http://daoscada.local/hmi-ui/upload", {
  method: "POST",
  body: formData,
});
```

---

# 二、Designer 接口（绑点用）

> 请求designer后端接口服务

- 使用统一的接口前缀，反向代理到designer后端接口服务（Java/SpringBoot 框架）；
- daoscada.local 演示环境中，接口前缀（BASE_URL）为 `/scadaBackApi`；
- 正式环境中需要在请求头中添加 bearer token
  - 页面登录后，token 会经JSON序列化后保存在 `localStorage['lsiot-ui:token']` 中
- 响应 Content-Type: application/json，内容以固定格式封装：
  ```jsonc
  {
    "code": "0", // 成功时返回字符串"0"，失败时返回异常状态码，例如"auth.TokenHasExpired"表示token过期
    "msg": "ok", // 请求失败时提示错误信息
    "reqId": null, // 可忽略
    "data": {...} // 成功时返回数据，失败时返回 null
  }
  ```
- 各类ID使用雪花算法生成，一般是19位数字的字符串（前端注意不要转为 number 类型，精度不够会丢失有效数字），全局唯一。

## 1. 项目列表

```http
POST {BASE_URL}/api/project/queryProjects HTTP/1.1
Content-Type: application/json
Authorization: Bearer {token}
```

### 请求参数

- 无请求参数

### 响应

- 返回包含所有项目的对象数组（不分页）

```jsonc
{
  "code": "0",
  "msg": "ok",
  "reqId": null,
  "data": [
    // 项目列表
    {
      "id": "1234567890123456789", // 项目ID（雪花ID，或者字符串"0"表示"公共项目"）
      "name": "项目1", // 显示的项目名称（全局唯一）
      "description": "", // 项目描述（没啥用，可作为 tooltip 显示）
      "tags": [], // 标签（字符串数组，也没啥用）
    },
    // ...
  ],
}
```

### 示例

```js
const token = JSON.parse(localStorage["lsiot-ui:token"]);
const res = await fetch(
  "http://daoscada.local/scadaBackApi/api/project/queryProjects",
  {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  },
).then((res) => res.json());

console.log(res.data);
```

## 2. 项目下设备列表

```http
POST {BASE_URL}/api/device/list HTTP/1.1
Content-Type: application/json
Authorization: Bearer {token}
```

### 请求参数（JSON body）

- projectId: 项目ID（字符串）

### 响应

- 返回项目下所有设备的对象数组（不分页，设备对象不含属性列表）

```jsonc
{
  "code": "0",
  "msg": "ok",
  "reqId": null,
  "data": [
    // 设备列表
    {
      "id": "1234567890123456789", // 项目ID（雪花ID）
      "name": "设备1", // 显示的设备名称（同项目下唯一）
      "description": "", // 设备描述（没啥用，可作为 tooltip 显示）
      "tags": [], // 标签（字符串数组，也没啥用）
      "projectId": "1234567890123456789", // 所属项目ID（字符串或数字"0"表示"公共项目"）
      "projectName": "项目1", // 所属项目名称
      "templateId": "1234567890123456789", // 继承的设备模板ID（1 表示通用模板）
      "templateName": "设备模板1", // 继承的设备模板名称（通用模板时为 null）
    },
    // ...
  ],
}
```

### 示例

```js
const projectId = "1909786813380186113";
const token = JSON.parse(localStorage["lsiot-ui:token"]);
const res = await fetch("http://daoscada.local/scadaBackApi/api/device/list", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ projectId }),
}).then((res) => res.json());

console.log(res.data);
```

## 3. 设备详情（属性列表）

```http
GET {BASE_URL}/api/device/queryInfo/{deviceId} HTTP/1.1
Authorization: Bearer {token}
```

### 请求参数（路径参数）

- deviceId: 设备ID（字符串）

### 响应

- 返回单个设备详情，包含其下所有属性列表（不分页）

```jsonc
{
  "code": "0",
  "msg": "ok",
  "reqId": null,
  "data": {
    // 设备详情
    "id": "1234567890123456789", // 设备ID（雪花ID）
    "name": "设备1", // 设备名称
    "description": "", // 设备描述
    "tags": [], // 标签
    "projectId": "1234567890123456789", // 所属项目ID（字符串或数字"0"表示"公共项目"）
    "projectName": "项目1", // 所属项目名称
    "templateId": "1234567890123456789", // 继承的设备模板ID（1 表示通用模板）
    "templateName": "设备模板1", // 继承的设备模板名称（通用模板时为 null）
    "properties": [
      // 设备属性列表
      {
        "id": "1234567890123456789", // 属性ID（雪花ID）
        "name": "属性1", // 属性名称（同设备下唯一）
        "description": "", // 属性描述
        "tags": [], // 属性标签
        "dataType": "double", // 属性数据类型（取值：double、int、bool、string）
        "dataTypeDesc": "浮点型", // 属性数据类型对应的显示名称（浮点型、整型、布尔型、字符型）
        "unit": "℃", // 单位（可能为 null）
        "defaultValue": null, // 默认值（可能为 null，仅影响数据采集，对界面展示没啥用）
        "upward": true, // 是否允许下行控制（注意!!! 此字段名称与实际含义相反，此为历史遗留的bug）
        "recordHistory": true, // 是否记录历史数据（用于在设计界面时判断是否允许对此属性执行历史数据查询操作）
        "objectId": "1234567890123456789", // 不要使用此字段！（字段含义：如果属性是从设备模板继承的，此字段值为模板ID，否则属性是设备的自身属性，此字段值与设备ID相同）
      },
      // ...
    ],
  },
}
```

### 示例

```js
const deviceId = "1955438815531266049";
const token = JSON.parse(localStorage["lsiot-ui:token"]);
const res = await fetch(
  `http://daoscada.local/scadaBackApi/api/device/queryInfo/${deviceId}`,
  {
    headers: { Authorization: `Bearer ${token}` },
  },
).then((res) => res.json());

console.log(res.data);
```

# 三、其他接口

> 待完善，暂时用不到

## 1. 当前用户信息查询（检查登录状态）

## 2. 用户登录（获取token）

## 3. 登录状态续期（refreshToken）

## 4. 用户登出

## 5. 读取属性实时值（单个/批量）

## 6. 属性下行控制（单个/批量）

## 7. 属性历史数据查询

## 8. 当前未恢复报警列表查询
