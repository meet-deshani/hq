-- Create Organisations table
CREATE TABLE IF NOT EXISTS organisations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    industry VARCHAR(150),
    initials VARCHAR(10),
    color VARCHAR(50) DEFAULT '#C8B6FF',
    note VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create Products table
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    organisation_id INTEGER REFERENCES organisations(id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    code VARCHAR(100) UNIQUE NOT NULL,
    description VARCHAR(255),
    status VARCHAR(50) DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create Workspaces table
CREATE TABLE IF NOT EXISTS workspaces (
    id SERIAL PRIMARY KEY,
    organisation_id INTEGER REFERENCES organisations(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    name VARCHAR(150) NOT NULL,
    slug VARCHAR(100),
    icon VARCHAR(100) DEFAULT 'grid',
    description VARCHAR(255),
    status VARCHAR(50) DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create Roles table
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    organisation_id INTEGER REFERENCES organisations(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_roles_org_name UNIQUE (organisation_id, name)
);


-- Create Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(150) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(150) NOT NULL,
    role_id INTEGER REFERENCES roles(id) ON DELETE SET NULL,
    organisation_id INTEGER REFERENCES organisations(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create Permissions table
CREATE TABLE IF NOT EXISTS permissions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    code VARCHAR(100) UNIQUE NOT NULL,
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create Role-Permissions mapping table
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INTEGER REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- Create Indexes for performance
CREATE INDEX IF NOT EXISTS idx_organisations_slug ON organisations(slug);
CREATE INDEX IF NOT EXISTS idx_products_org_id ON products(organisation_id);
CREATE INDEX IF NOT EXISTS idx_products_code ON products(code);
CREATE INDEX IF NOT EXISTS idx_workspaces_org_id ON workspaces(organisation_id);
CREATE INDEX IF NOT EXISTS idx_workspaces_product_id ON workspaces(product_id);
CREATE INDEX IF NOT EXISTS idx_roles_org_id ON roles(organisation_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id);
CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(organisation_id);
CREATE INDEX IF NOT EXISTS idx_role_permissions_role_id ON role_permissions(role_id);

