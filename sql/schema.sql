CREATE SCHEMA lab_data;

-- Dates format: YYYY-MM-DD

-- Sites table
CREATE TABLE lab_data.sampling_sites (
    site_name TEXT PRIMARY KEY,
    country TEXT NOT NULL DEFAULT 'Poland',
    region TEXT,
    county TEXT
);

-- Individuals table
CREATE TABLE lab_data.individuals (
    lab_id TEXT PRIMARY KEY,
    project_id TEXT,
    site_name TEXT NOT NULL REFERENCES lab_data.sampling_sites(site_name) ON UPDATE CASCADE,
    date_ce_start INTEGER,
    date_ce_stop INTEGER,
    date_ce_median INTEGER,
    epoch TEXT,
    time_period TEXT,
    period_order INTEGER,
    contact_person TEXT,
    collection_date DATE,
    coord_ns FLOAT,
    coord_we FLOAT,
    grave_no TEXT
);

-- Processed samples table
CREATE TABLE lab_data.processed_samples (
    lab_id TEXT NOT NULL REFERENCES lab_data.individuals(lab_id) ON UPDATE CASCADE,
    material_id TEXT NOT NULL,
    material_description TEXT,
    bleached BOOLEAN,
    scraped BOOLEAN,
    uved BOOLEAN,
    prep_date DATE NOT NULL,
    prep_operator TEXT NULL,
    lysis_method TEXT DEFAULT 'Rohland et al. 2018',
    lysis_date DATE,
    lysis_operator TEXT, 
    PRIMARY KEY (lab_id, material_id)
);

CREATE TABLE lab_data.dna_extractions (
    lab_id TEXT NOT NULL,
    material_id TEXT NOT NULL,
    times_extracted INTEGER NOT NULL,
    extract_operator TEXT,
    extract_date DATE,
    extract_method TEXT DEFAULT 'Rohland et al. 2018',
    extract_remarks TEXT,
    udg_treatment TEXT,
    udg_date DATE,
    udg_method TEXT,
    udg_remarks TEXT,
    FOREIGN KEY (lab_id, material_id)
        REFERENCES lab_data.processed_samples(lab_id, material_id) 
        ON UPDATE CASCADE,
    PRIMARY KEY (lab_id, material_id, times_extracted)
);


CREATE TABLE lab_data.libraries (
    library_id TEXT PRIMARY KEY,
    lab_id TEXT NOT NULL,
    material_id TEXT NOT NULL,
    times_extracted INTEGER NOT NULL,
    library_type TEXT NOT NULL DEFAULT 'Single',
    library_date DATE,
    library_operator TEXT,
    library_remarks TEXT,
    elution_date DATE,
    elution_operator TEXT,
    elution_remarks TEXT,
    qPCR_date DATE,
    qPCR_operator TEXT,
    qPCR_method TEXT DEFAULT 'AA Biotech',
    qPCR_remarks TEXT,
    log_onset INTEGER,
    library_concentration FLOAT,
    FOREIGN KEY (lab_id, material_id, times_extracted)
        REFERENCES lab_data.dna_extractions(lab_id, material_id, times_extracted)
        ON UPDATE CASCADE
);

CREATE TABLE lab_data.sequencing_run (
    sequencing_id TEXT PRIMARY KEY,
    sequencing_date DATE
);

CREATE TABLE lab_data.indexing (
    library_id TEXT NOT NULL REFERENCES lab_data.libraries(library_id) ON UPDATE CASCADE,
    times_indexed INTEGER NOT NULL,
    sequencing_id TEXT NULL REFERENCES lab_data.sequencing_run(sequencing_id) ON UPDATE CASCADE,
    index_used TEXT,
    index_date DATE,
    index_operator TEXT,
    index_method TEXT DEFAULT 'Cx, XX ul',
    cycles INTEGER,
    index_remarks TEXT,
    PRIMARY KEY (library_id, times_indexed),
    UNIQUE (library_id, sequencing_id)
);

CREATE TABLE lab_data.dna_sequencing (
    fastq_name TEXT PRIMARY KEY,
    fastq_path_r1 TEXT, 
    fastq_path_r2 TEXT,
    library_id TEXT NOT NULL,
    sequencing_id TEXT NOT NULL,
    index_p7 TEXT,
    index_P5 TEXT,
    fastq_folder TEXT,
    raw_reads INTEGER,
    shotgun_enriched TEXT DEFAULT 'No',
    suffix1 TEXT,
    suffix2 TEXT,
    suffix3 TEXT,
    suffix4 TEXT,
    suffix5 TEXT,
    FOREIGN KEY (library_id, sequencing_id)
        REFERENCES lab_data.indexing(library_id, sequencing_id)
        ON UPDATE CASCADE
);

CREATE TABLE lab_data.dna_mapping (
    fastq_name TEXT PRIMARY KEY REFERENCES lab_data.dna_sequencing(fastq_name) ON UPDATE CASCADE,
    bam_path TEXT,
    merged BOOLEAN DEFAULT FALSE,
    tot_reads_map INTEGER,
    unique_reads_map INTEGER,
    endo_dna FLOAT   
);

CREATE TABLE lab_data.sex_estimation (
    fastq_name TEXT PRIMARY KEY REFERENCES lab_data.dna_sequencing(fastq_name) ON UPDATE CASCADE,
    rx FLOAT,
    ci_low_95 FLOAT,
    ci_high_95 FLOAT,
    sex_assignment TEXT,
    sex_assignment_min_10k_reads TEXT
);

CREATE OR REPLACE VIEW lab_data.individuals_status AS
SELECT 
    i.lab_id, 
    -- 1. Processing (es: "PL626T (2026-04-20)")
    STRING_AGG(DISTINCT ps.material_id || ' (' || ps.prep_date::DATE::TEXT || ')', ' | ') AS processing_info,
    -- 2. Count
    COUNT(DISTINCT de.times_extracted) AS num_extractions,
    COUNT(DISTINCT ix.sequencing_id) AS times_sequenced,
    -- 3. Extractions: DATA (Materiale ext.N)
    STRING_AGG(DISTINCT de.extract_date::TEXT || ' (' || i.lab_id || ps.material_id || de.times_extracted || ')', ' | ') AS extract_dates,
    STRING_AGG(DISTINCT COALESCE(de.udg_date::TEXT, 'No UDG') || ' (' || i.lab_id || ps.material_id || de.times_extracted || ')', ' | ') AS udg_dates,
    -- 4. Libraries: DATA (Library_ID)
    STRING_AGG(DISTINCT lib.library_date::TEXT || ' (' || lib.library_id || ')', ' | ') AS library_dates,
    STRING_AGG(DISTINCT lib.elution_date::TEXT || ' (' || lib.library_id || ')', ' | ') AS elution_dates,
    -- 5. Indexing & qPCR: DATA (Library_ID [Seq_ID])
    STRING_AGG(DISTINCT ix.index_date::TEXT || ' (' || lib.library_id || ' [' || ix.sequencing_id || '])', ' | ') AS index_dates,
    STRING_AGG(DISTINCT lib.qpcr_date::TEXT || ' (' || lib.library_id || ' [' || ix.sequencing_id || '])', ' | ') AS qpcr_dates,
    -- 6. Sequencing Runs: DATA (Run_ID)
    STRING_AGG(DISTINCT sr.sequencing_date::TEXT || ' (' || sr.sequencing_id || ')', ' | ') AS sequencing_run_dates,
    -- 7. Analysis
    STRING_AGG(DISTINCT ds.raw_reads::TEXT || ' (' || ds.library_id || ')', ' | ') AS raw_reads_info,
    STRING_AGG(DISTINCT dm.endo_dna::TEXT || '% (' || dm.fastq_name || ')', ' | ') AS endo_dna_info,
    STRING_AGG(DISTINCT se.sex_assignment || ' (' || se.fastq_name || ')', ' | ') AS sex_info
FROM lab_data.individuals i
LEFT JOIN lab_data.processed_samples ps 
    ON i.lab_id = ps.lab_id
LEFT JOIN lab_data.dna_extractions de 
    ON ps.lab_id = de.lab_id AND ps.material_id = de.material_id
LEFT JOIN lab_data.libraries lib 
    ON de.lab_id = lib.lab_id AND de.material_id = lib.material_id AND de.times_extracted = lib.times_extracted
LEFT JOIN lab_data.indexing ix 
    ON lib.library_id = ix.library_id
LEFT JOIN lab_data.sequencing_run sr 
    ON ix.sequencing_id = sr.sequencing_id
LEFT JOIN lab_data.dna_sequencing ds 
    ON ix.library_id = ds.library_id AND ix.sequencing_id = ds.sequencing_id
LEFT JOIN lab_data.dna_mapping dm 
    ON ds.fastq_name = dm.fastq_name
LEFT JOIN lab_data.sex_estimation se 
    ON ds.fastq_name = se.fastq_name
GROUP BY i.lab_id;
