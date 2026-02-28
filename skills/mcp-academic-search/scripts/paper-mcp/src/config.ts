import * as dotenv from 'dotenv';

// 加载环境变量：
// 1. 本地开发时，从.env文件加载
// 2. 在Smithery部署时，从配置文件中加载
dotenv.config();

// For logging purposes only in development
if (process.env.NODE_ENV !== 'production') {
  console.log('Environment variables loaded, OPENALEX_EMAIL available:', process.env.OPENALEX_EMAIL ? 'Yes' : 'No');
}

export const OPENALEX_CONFIG = {
  /**
   * OpenAlex API Email
   * 1. 本地开发：在项目根目录创建.env文件并设置 OPENALEX_EMAIL=你的邮箱
   * 2. Smithery部署：在Smithery平台配置OPENALEX_EMAIL
   */
  EMAIL: process.env.OPENALEX_EMAIL ?? "2621418421@qq.com",

  /** OpenAlex API 服务器地址 */
  API_URL: "https://api.openalex.org",

  /** 超时 ms */
  TIMEOUT: 30000,
};
