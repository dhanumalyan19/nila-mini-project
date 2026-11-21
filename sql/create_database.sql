-- Open in MySQL Workbench using your existing local administrator connection.
-- First confirm that an existing schema named nila, if present, belongs to this app.
-- This file does not create accounts, set passwords, or drop any database.
CREATE DATABASE IF NOT EXISTS nila
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

-- Nila needs MySQL >= 8.0.16 and the InnoDB storage engine.
SELECT VERSION() AS mysql_version,
       @@default_storage_engine AS default_storage_engine,
       @@sql_mode AS sql_mode;

