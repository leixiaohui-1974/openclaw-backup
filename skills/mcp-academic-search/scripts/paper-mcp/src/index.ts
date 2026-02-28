#!/usr/bin/env node
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

// ✅ 引入论文搜索工具
import { paperSearch } from "./tools/paperSearch.js";

// 创建 MCP server
const server = new Server(
  {
    name: "PaperMCP",
    version: "0.1.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// 🛠️ 工具：列出论文搜索工具
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: paperSearch.name,
        description: paperSearch.description,
        inputSchema: paperSearch.parameters
      }
    ]
  };
});

// 🛠️ 工具：执行工具
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  switch (request.params.name) {
    case "paper_search": {
      const query = String(request.params.arguments?.query);
      const research_focus = request.params.arguments?.research_focus ? String(request.params.arguments.research_focus) : undefined;
      const academic_level = request.params.arguments?.academic_level ? String(request.params.arguments.academic_level) : undefined;
      const time_scope = request.params.arguments?.time_scope ? String(request.params.arguments.time_scope) : undefined;
      const field_specificity = request.params.arguments?.field_specificity ? String(request.params.arguments.field_specificity) : undefined;
      const citation_threshold = request.params.arguments?.citation_threshold ? String(request.params.arguments.citation_threshold) : undefined;
      const include_preprints = request.params.arguments?.include_preprints ? Boolean(request.params.arguments.include_preprints) : undefined;
      const author_reputation = request.params.arguments?.author_reputation ? String(request.params.arguments.author_reputation) : undefined;
      const num_results = request.params.arguments?.num_results ? Number(request.params.arguments.num_results) : undefined;
      const exclude_keywords = request.params.arguments?.exclude_keywords ? String(request.params.arguments.exclude_keywords) : undefined;
      
      return await paperSearch.run({ 
        query, 
        research_focus, 
        academic_level, 
        time_scope, 
        field_specificity, 
        citation_threshold, 
        include_preprints, 
        author_reputation, 
        num_results, 
        exclude_keywords 
      });
    }

    default:
      throw new Error("Unknown tool");
  }
});

// 启动 server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error) => {
  console.error("Server error:", error);
  process.exit(1);
});
