# Company details

- Outboard Parts Warehouse
- Production site: https://odoo.outboardpartswarehouse.com/
- Local development: http://localhost:8069/
- Primary Business: Buying outboard motors and parting them out on eBay and Shopify.

# Development Tools

- IntelliJ IDEA Ultimate 2024.3.1.1
- Odoo Framework Integration plugin
- Odoo 18
- Owl.js 2.0
- Python 3.13.1
- Shopify GraphQL API

# Code Standards

- Pythonic, clean, and elegant code
- Follow Odoo core development patterns and best practices
- Proper use of inheritance and extension mechanisms
- Follow standard Odoo project structure and logging patterns
- PEP 8
- Descriptive function and variable names that convey purpose clearly instead of comments.
- No comments or docstrings in returned code

# Workflow

- Use the jetbrains mcpServer plugin to get the context directly from IntelliJ.
- Retrieve and examine relevant code, models, and views before analysis or explanation.
- Check for dependencies that may be relevant to the issue.
- use the brave-search MCP tool to search the web for new or related information if needed.
- use the postgre MCP tool to query the database for relevant information if needed
- use the apply-patch MCP tool to apply changes to the code.

# Deployment

- opw-prod: Production environment
- opw-testing: Testing environment
- opw-dev: Development environment
- GitHub pushes to opw-prod/opw-testing trigger deployments
