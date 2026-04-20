-- 1. Insert a site
INSERT INTO lab_data.sampling_sites (site_name, country) 
VALUES ('Imaginary Land', 'Poland');

-- 2. Insert an individual
INSERT INTO lab_data.individuals (lab_id, site_name, project_id) 
VALUES ('PL001', 'Imaginary Land', 'Project-test');

-- 3. 2 samples for the same individual
INSERT INTO lab_data.processed_samples (lab_id, material, prep_operator) 
VALUES ('PL001', 'T', 'FL'),
       ('PL001', 'A', 'FL');

-- 4. 2 extractions for the tooth
INSERT INTO lab_data.dna_extractions (lab_id, material, times_extracted, extract_date) 
VALUES ('PL001', 'T', 1, '2024-05-01'),
       ('PL001', 'T', 2, '2024-05-10');

-- 5. Library for the first extraction
INSERT INTO lab_data.libraries (library_id, lab_id, material, times_extracted, library_operator)
VALUES ('LIB_P1_T1', 'PL001', 'T', 1, 'MM');