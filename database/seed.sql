-- Seed default Organisations
INSERT INTO organisations (name, slug, industry, initials, color, note) VALUES
('Z9S-AI', 'z9s-ai', 'AI Implementation', 'Z', '#C8B6FF', 'Z9S-AI operating system.')
ON CONFLICT (slug) DO NOTHING;

-- Seed default Products
INSERT INTO products (organisation_id, name, code, description, status) VALUES
((SELECT id FROM organisations WHERE slug = 'z9s-ai'), 'HQ Portal', 'hq', 'Core HQ platform product', 'Active')
ON CONFLICT (code) DO NOTHING;

-- Seed default Workspaces
INSERT INTO workspaces (organisation_id, product_id, name, slug, icon, description, status) VALUES
((SELECT id FROM organisations WHERE slug = 'z9s-ai'), (SELECT id FROM products WHERE code = 'hq'), 'HQ', 'hq', 'grid', 'HQ main workspace', 'Active'),
((SELECT id FROM organisations WHERE slug = 'z9s-ai'), (SELECT id FROM products WHERE code = 'hq'), 'Config', 'config', 'sliders', 'Configuration workspace', 'Active'),
((SELECT id FROM organisations WHERE slug = 'z9s-ai'), (SELECT id FROM products WHERE code = 'hq'), 'Users', 'users', 'users', 'User management workspace', 'Active');

-- Seed default Roles
INSERT INTO roles (organisation_id, name, description) VALUES
((SELECT id FROM organisations WHERE slug = 'z9s-ai'), 'Admin', 'Administrator with full permissions across all workspaces'),
((SELECT id FROM organisations WHERE slug = 'z9s-ai'), 'Operator', 'Standard operator with access to general operations'),
((SELECT id FROM organisations WHERE slug = 'z9s-ai'), 'Viewer', 'Read-only access to workspaces')
ON CONFLICT DO NOTHING;

-- Seed default Permissions
INSERT INTO permissions (name, code, description) VALUES
('Read Users', 'users:read', 'Ability to list and view users'),
('Create Users', 'users:write', 'Ability to create or modify users'),
('Delete Users', 'users:delete', 'Ability to delete users'),
('Read Roles', 'roles:read', 'Ability to view roles list'),
('Write Roles', 'roles:write', 'Ability to create and manage roles'),
('Read Permissions', 'permissions:read', 'Ability to view permissions list'),
('Grant Permissions', 'permissions:grant', 'Ability to grant permissions to roles'),
('Revoke Permissions', 'permissions:revoke', 'Ability to revoke permissions from roles'),
('Read Dashboard', 'dashboard:read', 'Ability to view HQ dashboard metrics'),
('Read Organisations', 'organisations:read', 'Ability to view organisations'),
('Write Organisations', 'organisations:write', 'Ability to create and manage organisations'),
('Read Products', 'products:read', 'Ability to view products'),
('Write Products', 'products:write', 'Ability to create and manage products'),
('Read Workspaces', 'workspaces:read', 'Ability to view workspaces'),
('Write Workspaces', 'workspaces:write', 'Ability to create and manage workspaces')
ON CONFLICT (code) DO NOTHING;

-- Map all permissions to Admin role
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.name = 'Admin'
ON CONFLICT DO NOTHING;

