with open('src/maestro/api/routes/ui.py', 'r') as f:
    lines = f.readlines()

out_lines = []
in_func_def = False
for line in lines:
    if "from maestro.services.ui import UIService" in line:
        out_lines.append(line)
        out_lines.append("from maestro.auth.dependencies import get_current_user\n")
        out_lines.append("from maestro.database.models import User\n")
        continue

    if line.startswith("async def "):
        in_func_def = True
    
    if in_func_def:
        if "):" in line:
            line = line.replace("):", ", current_user: User = Depends(get_current_user)):")
            in_func_def = False
        elif ") ->" in line:
            line = line.replace(") ->", ", current_user: User = Depends(get_current_user)) ->")
            in_func_def = False
            
    out_lines.append(line)

content = "".join(out_lines)

# Now templates.TemplateResponse
content = content.replace('{\n            "executions":', '{\n            "current_user": current_user,\n            "executions":')
content = content.replace('{\n            "execution":', '{\n            "current_user": current_user,\n            "execution":')
content = content.replace('{"yaml_content":', '{"current_user": current_user, "yaml_content":')
content = content.replace('{"error":', '{"current_user": current_user, "error":')
content = content.replace('{\n            "settings":', '{\n            "current_user": current_user,\n            "settings":')
content = content.replace('{\n            "descriptors":', '{\n            "current_user": current_user,\n            "descriptors":')
content = content.replace('{\n            "schedules":', '{\n            "current_user": current_user,\n            "schedules":')
content = content.replace('{"events":', '{"current_user": current_user, "events":')
content = content.replace('return templates.TemplateResponse(request, "index.html")', 'return templates.TemplateResponse(request, "index.html", {"current_user": current_user})')
content = content.replace('return templates.TemplateResponse(\n        request,\n        "releases.html",\n    )', 'return templates.TemplateResponse(\n        request,\n        "releases.html",\n        {"current_user": current_user}\n    )')
content = content.replace('return templates.TemplateResponse(\n        request,\n        "releases_archived.html",\n    )', 'return templates.TemplateResponse(\n        request,\n        "releases_archived.html",\n        {"current_user": current_user}\n    )')
content = content.replace('return templates.TemplateResponse(request, "schedules.html")', 'return templates.TemplateResponse(request, "schedules.html", {"current_user": current_user})')

# Fix a trailing comma if any
content = content.replace('(request: Request, current_user: User = Depends(get_current_user))', '(request: Request, current_user: User = Depends(get_current_user))')

with open('src/maestro/api/routes/ui.py', 'w') as f:
    f.write(content)
