"""Initial schema — all tables, indexes, constraints.

Squashed from 28 migrations (001–027 + merge d7af925de530).

Revision ID: 001
Create Date: 2026-03-29
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ── precipitation_data ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE precipitation_data (
            id SERIAL PRIMARY KEY,
            geom geometry(Point, 2180) NOT NULL,
            duration VARCHAR(10) NOT NULL,
            probability DOUBLE PRECISION NOT NULL,
            precipitation_mm DOUBLE PRECISION NOT NULL,
            source VARCHAR(50) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT positive_precipitation CHECK (precipitation_mm >= 0),
            CONSTRAINT valid_duration CHECK (duration IN (
                '5min','10min','15min','30min','45min',
                '1h','1.5h','2h','3h','6h','12h','18h','24h','36h','48h','72h'
            )),
            CONSTRAINT valid_probability CHECK (probability IN (
                0.01,0.02,0.03,0.05,0.1,0.2,0.3,0.5,1,2,3,5,10,
                20,30,40,50,60,70,80,90,95,98,98.5,99,99.5,99.9
            )),
            CONSTRAINT unique_precipitation_scenario UNIQUE (geom, duration, probability)
        )
    """)
    op.execute("CREATE INDEX idx_precipitation_geom ON precipitation_data USING GIST (geom)")
    op.execute("CREATE INDEX idx_precipitation_duration ON precipitation_data USING btree (duration)")
    op.execute("CREATE INDEX idx_precipitation_probability ON precipitation_data USING btree (probability)")
    op.execute("CREATE INDEX idx_precipitation_scenario ON precipitation_data USING btree (duration, probability)")

    # ── land_cover ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE land_cover (
            id SERIAL PRIMARY KEY,
            geom geometry(MultiPolygon, 2180) NOT NULL,
            category VARCHAR(50) NOT NULL,
            cn_value INTEGER NOT NULL,
            imperviousness DOUBLE PRECISION,
            bdot_class VARCHAR(20),
            CONSTRAINT valid_category CHECK (category IN (
                'las','łąka','grunt_orny','zabudowa_mieszkaniowa',
                'zabudowa_przemysłowa','droga','woda','inny'
            )),
            CONSTRAINT valid_cn CHECK (cn_value >= 0 AND cn_value <= 100),
            CONSTRAINT valid_imperviousness CHECK (
                imperviousness IS NULL OR (imperviousness >= 0 AND imperviousness <= 1)
            )
        )
    """)
    op.execute("CREATE INDEX idx_land_cover_geom ON land_cover USING GIST (geom)")
    op.execute("CREATE INDEX idx_category ON land_cover USING btree (category)")
    op.execute("CREATE INDEX idx_cn_value ON land_cover USING btree (cn_value)")

    # ── stream_network ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE stream_network (
            id SERIAL PRIMARY KEY,
            geom geometry(LineString, 2180) NOT NULL,
            name VARCHAR(100),
            length_m DOUBLE PRECISION,
            strahler_order INTEGER,
            source VARCHAR(50),
            upstream_area_km2 DOUBLE PRECISION,
            mean_slope_percent DOUBLE PRECISION,
            threshold_m2 INTEGER NOT NULL,
            segment_idx INTEGER,
            is_real_stream BOOLEAN,
            is_sewer_augmented BOOLEAN DEFAULT false,
            CONSTRAINT positive_length CHECK (length_m IS NULL OR length_m > 0),
            CONSTRAINT valid_strahler CHECK (strahler_order IS NULL OR strahler_order > 0)
        )
    """)
    op.execute("CREATE INDEX idx_stream_network_geom ON stream_network USING GIST (geom)")
    op.execute("CREATE INDEX idx_stream_geom_dem_derived ON stream_network USING GIST (geom) WHERE source = 'DEM_DERIVED'")
    op.execute("CREATE INDEX idx_stream_geom_t1000 ON stream_network USING GIST (geom) WHERE threshold_m2 = 1000")
    op.execute("CREATE INDEX idx_stream_geom_t10000 ON stream_network USING GIST (geom) WHERE threshold_m2 = 10000")
    op.execute("CREATE INDEX idx_stream_geom_t100000 ON stream_network USING GIST (geom) WHERE threshold_m2 = 100000")
    op.execute("CREATE INDEX idx_stream_name ON stream_network USING btree (name)")
    op.execute("CREATE INDEX idx_stream_threshold ON stream_network USING btree (threshold_m2, strahler_order)")
    op.execute("CREATE INDEX idx_stream_threshold_segidx ON stream_network USING btree (threshold_m2, segment_idx)")
    op.execute("CREATE INDEX idx_stream_upstream_area ON stream_network USING btree (upstream_area_km2)")
    op.execute("CREATE INDEX idx_strahler_order ON stream_network USING btree (strahler_order)")
    op.execute("""
        CREATE UNIQUE INDEX idx_stream_unique ON stream_network
        USING btree (COALESCE(name, ''), threshold_m2, ST_GeoHash(ST_Transform(geom, 4326), 12))
    """)

    # ── depressions ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE depressions (
            id SERIAL PRIMARY KEY,
            geom geometry(Polygon, 2180) NOT NULL,
            volume_m3 DOUBLE PRECISION NOT NULL,
            area_m2 DOUBLE PRECISION NOT NULL,
            max_depth_m DOUBLE PRECISION NOT NULL,
            mean_depth_m DOUBLE PRECISION
        )
    """)
    op.execute("CREATE INDEX idx_depressions_geom ON depressions USING GIST (geom)")
    op.execute("CREATE INDEX idx_depressions_volume ON depressions USING btree (volume_m3)")
    op.execute("CREATE INDEX idx_depressions_area ON depressions USING btree (area_m2)")
    op.execute("CREATE INDEX idx_depressions_max_depth ON depressions USING btree (max_depth_m)")

    # ── stream_catchments ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE stream_catchments (
            id SERIAL PRIMARY KEY,
            geom geometry(MultiPolygon, 2180) NOT NULL,
            segment_idx INTEGER NOT NULL,
            threshold_m2 INTEGER NOT NULL,
            area_km2 DOUBLE PRECISION NOT NULL,
            mean_elevation_m DOUBLE PRECISION,
            mean_slope_percent DOUBLE PRECISION,
            strahler_order INTEGER,
            downstream_segment_idx INTEGER,
            elevation_min_m DOUBLE PRECISION,
            elevation_max_m DOUBLE PRECISION,
            perimeter_km DOUBLE PRECISION,
            stream_length_km DOUBLE PRECISION,
            elev_histogram JSONB,
            hydraulic_length_km DOUBLE PRECISION,
            max_flow_dist_m DOUBLE PRECISION,
            longest_flow_path_geom geometry(LineString, 2180),
            divide_flow_path_geom geometry(LineString, 2180)
        )
    """)
    op.execute("CREATE INDEX idx_catchments_geom ON stream_catchments USING GIST (geom)")
    op.execute("CREATE INDEX idx_catchment_geom_t1000 ON stream_catchments USING GIST (geom) WHERE threshold_m2 = 1000")
    op.execute("CREATE INDEX idx_catchment_geom_t10000 ON stream_catchments USING GIST (geom) WHERE threshold_m2 = 10000")
    op.execute("CREATE INDEX idx_catchment_geom_t100000 ON stream_catchments USING GIST (geom) WHERE threshold_m2 = 100000")
    op.execute("CREATE INDEX idx_catchments_area ON stream_catchments USING btree (area_km2)")
    op.execute("CREATE INDEX idx_catchments_threshold ON stream_catchments USING btree (threshold_m2, strahler_order)")
    op.execute("CREATE INDEX idx_catchments_threshold_segment ON stream_catchments USING btree (threshold_m2, segment_idx)")
    op.execute("CREATE INDEX idx_catchments_downstream ON stream_catchments USING btree (threshold_m2, downstream_segment_idx)")
    op.execute("CREATE INDEX idx_catchments_flow_path_geom ON stream_catchments USING GIST (longest_flow_path_geom) WHERE longest_flow_path_geom IS NOT NULL")
    op.execute("CREATE INDEX idx_catchments_divide_flow_path_geom ON stream_catchments USING GIST (divide_flow_path_geom) WHERE divide_flow_path_geom IS NOT NULL")

    # ── soil_hsg ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE soil_hsg (
            id SERIAL PRIMARY KEY,
            geom geometry(MultiPolygon, 2180) NOT NULL,
            hsg_group VARCHAR(1) NOT NULL,
            area_m2 DOUBLE PRECISION NOT NULL,
            CONSTRAINT valid_hsg_group CHECK (hsg_group IN ('A','B','C','D'))
        )
    """)
    op.execute("CREATE INDEX idx_soil_hsg_geom ON soil_hsg USING GIST (geom)")
    op.execute("CREATE INDEX idx_soil_hsg_group ON soil_hsg USING btree (hsg_group)")

    # ── bdot_streams ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE bdot_streams (
            id SERIAL PRIMARY KEY,
            geom geometry(LineString, 2180) NOT NULL,
            layer_type VARCHAR(10) NOT NULL,
            name VARCHAR(200),
            length_m DOUBLE PRECISION
        )
    """)
    op.execute("CREATE INDEX idx_bdot_streams_geom ON bdot_streams USING GIST (geom)")
    op.execute("CREATE INDEX idx_bdot_streams_type ON bdot_streams USING btree (layer_type)")

    # ── sewer_nodes ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE sewer_nodes (
            id SERIAL PRIMARY KEY,
            geom geometry(Point, 2180) NOT NULL,
            node_type VARCHAR(20) NOT NULL,
            component_id INTEGER,
            depth_m DOUBLE PRECISION,
            invert_elev_m DOUBLE PRECISION,
            dem_elev_m DOUBLE PRECISION,
            burn_elev_m DOUBLE PRECISION,
            fa_value INTEGER,
            total_upstream_fa INTEGER,
            root_outlet_id INTEGER,
            nearest_stream_segment_idx INTEGER,
            source_type VARCHAR(20) NOT NULL DEFAULT 'topology_generated',
            rim_elev_m DOUBLE PRECISION,
            max_depth_m DOUBLE PRECISION,
            ponded_area_m2 DOUBLE PRECISION,
            outfall_type VARCHAR(20),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_node_type CHECK (node_type IN ('inlet','outlet','junction','storage')),
            CONSTRAINT chk_outlet_not_self CHECK (root_outlet_id <> id),
            CONSTRAINT sewer_nodes_root_outlet_id_fkey
                FOREIGN KEY (root_outlet_id) REFERENCES sewer_nodes(id)
        )
    """)
    op.execute("CREATE INDEX idx_sewer_nodes_geom ON sewer_nodes USING GIST (geom)")
    op.execute("CREATE INDEX idx_sewer_nodes_node_type ON sewer_nodes USING btree (node_type)")
    op.execute("CREATE INDEX idx_sewer_nodes_root_outlet_node_type ON sewer_nodes USING btree (root_outlet_id, node_type)")

    # ── sewer_network ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE sewer_network (
            id SERIAL PRIMARY KEY,
            geom geometry(LineString, 2180) NOT NULL,
            node_from_id INTEGER NOT NULL REFERENCES sewer_nodes(id),
            node_to_id INTEGER NOT NULL REFERENCES sewer_nodes(id),
            diameter_mm INTEGER,
            width_mm INTEGER,
            height_mm INTEGER,
            cross_section_shape VARCHAR(20),
            invert_elev_start_m DOUBLE PRECISION,
            invert_elev_end_m DOUBLE PRECISION,
            material VARCHAR(50),
            manning_n DOUBLE PRECISION,
            length_m DOUBLE PRECISION NOT NULL,
            slope_percent DOUBLE PRECISION,
            source VARCHAR(255) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_diameter_positive CHECK (diameter_mm IS NULL OR diameter_mm > 0),
            CONSTRAINT chk_length_positive CHECK (length_m > 0),
            CONSTRAINT chk_manning_range CHECK (manning_n IS NULL OR (manning_n > 0 AND manning_n < 1))
        )
    """)
    op.execute("CREATE INDEX idx_sewer_network_geom ON sewer_network USING GIST (geom)")
    op.execute("CREATE INDEX idx_sewer_network_node_from_id ON sewer_network USING btree (node_from_id)")
    op.execute("CREATE INDEX idx_sewer_network_node_to_id ON sewer_network USING btree (node_to_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sewer_network CASCADE")
    op.execute("DROP TABLE IF EXISTS sewer_nodes CASCADE")
    op.execute("DROP TABLE IF EXISTS bdot_streams CASCADE")
    op.execute("DROP TABLE IF EXISTS soil_hsg CASCADE")
    op.execute("DROP TABLE IF EXISTS stream_catchments CASCADE")
    op.execute("DROP TABLE IF EXISTS depressions CASCADE")
    op.execute("DROP TABLE IF EXISTS stream_network CASCADE")
    op.execute("DROP TABLE IF EXISTS land_cover CASCADE")
    op.execute("DROP TABLE IF EXISTS precipitation_data CASCADE")
