from app.modules.config_center.schemas import MigrationDryRunRead


def config_center_migration_plan() -> MigrationDryRunRead:
    return MigrationDryRunRead(
        source_project="/Volumes/TiPro9000/projects/archived/stock-analysis",
        legacy_counts={},
        planned_steps=[
            "Create t_system_config, t_config_value, and rebuilt t_config_option.",
            "Migrate Search, LLM, and Notification config objects from legacy config tables.",
            "Preserve encrypted values and fingerprints without printing secrets.",
            "Drop t_config_node, t_secret_key, and t_config_relation after validation.",
        ],
    )
