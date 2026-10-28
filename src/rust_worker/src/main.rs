mod models;
mod s3_client;
mod tika_client;

use base64::prelude::*;
use chrono::Utc;
use clap::Parser;
use log::{error, info, warn};
use models::{BatchInputEnvelope, BinaryFileItem, FinalBatchManifest, RawScrapedRecord};
use s3_client::RustFSS3Client;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::File;
use std::io::{self, Read};
use std::path::Path;
use std::time::Instant;
use tika_client::TikaClient;
use uuid::Uuid;

#[derive(Parser, Debug)]
#[command(name = "idci_rust_worker")]
#[command(about = "Rust Worker de Alto Rendimiento para Filtrado, Tika Fan-Out y Persistencia en RustFS")]
struct Args {
    /// Ruta del archivo JSON con los registros crudos del scraper, o '-' para leer desde stdin
    #[arg(short, long, default_value = "-")]
    input: String,

    /// Endpoint de RustFS S3
    #[arg(long, env = "S3_ENDPOINT_URL", default_value = "http://rustfs:9000")]
    s3_endpoint: String,

    /// Access Key de S3
    #[arg(long, env = "S3_ACCESS_KEY", default_value = "rustfsadmin")]
    s3_access_key: String,

    /// Secret Key de S3
    #[arg(long, env = "S3_SECRET_KEY", default_value = "rustfsadmin2026")]
    s3_secret_key: String,

    /// Bucket de destino
    #[arg(long, env = "S3_BUCKET", default_value = "opportunity-intelligence")]
    bucket: String,

    /// URL del servidor Apache Tika
    #[arg(long, env = "TIKA_URL", default_value = "http://tika:9998")]
    tika_url: String,

    /// Nombre de la institución o portal
    #[arg(long, env = "INSTITUTION_NAME", default_value = "idrc")]
    institution: String,

    /// Modo de prueba (dry-run): ejecuta validaciones y Tika sin escribir en S3
    #[arg(long, default_value_t = false)]
    dry_run: bool,
}

fn calculate_sha256(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hex::encode(hasher.finalize())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let start_time = Instant::now();
    let args = Args::parse();

    info!("================================================================================");
    info!("🦀 [IDCI Rust Worker] Iniciando ciclo de procesamiento y persistencia de datos");
    info!("   ├─ S3 Endpoint  : {}", args.s3_endpoint);
    info!("   ├─ S3 Bucket    : {}", args.bucket);
    info!("   ├─ Tika Endpoint: {}", args.tika_url);
    info!("   ├─ Institución  : {}", args.institution);
    info!("   └─ Dry-Run      : {}", args.dry_run);
    info!("================================================================================");

    // 1. Leer stream o archivo de entrada
    let mut input_data = String::new();
    if args.input == "-" {
        info!("[Rust Worker] Leyendo stream de registros crudos desde stdin...");
        io::stdin().read_to_string(&mut input_data)?;
    } else {
        info!("[Rust Worker] Leyendo registros desde archivo: {}", args.input);
        let mut file = File::open(&args.input)?;
        file.read_to_string(&mut input_data)?;
    }

    if input_data.trim().is_empty() {
        warn!("[Rust Worker] La entrada está vacía. Finalizando.");
        return Ok(());
    }

    // Deserializar tolerantemente: soporta BatchInputEnvelope o Vec<RawScrapedRecord>
    let mut records: Vec<RawScrapedRecord> = Vec::new();
    let mut batch_id = Uuid::new_v4().to_string();
    let mut resolved_institution = args.institution.clone();
    let mut resolved_spider: Option<String> = None;
    let mut resolved_target_table: Option<String> = None;
    let mut resolved_source_system: Option<String> = None;

    if let Ok(envelope) = serde_json::from_str::<BatchInputEnvelope>(&input_data) {
        if let Some(bid) = envelope.batch_id {
            batch_id = bid;
        }
        if let Some(inst) = envelope.institution_name {
            if !inst.trim().is_empty() {
                resolved_institution = inst;
            }
        }
        if let Some(sp) = envelope.spider {
            if !sp.trim().is_empty() {
                resolved_spider = Some(sp);
            }
        }
        if let Some(tbl) = envelope.target_table {
            if !tbl.trim().is_empty() {
                resolved_target_table = Some(tbl);
            }
        }
        if let Some(src) = envelope.source_system {
            if !src.trim().is_empty() {
                resolved_source_system = Some(src);
            }
        }
        records = envelope.records;
    } else if let Ok(arr) = serde_json::from_str::<Vec<RawScrapedRecord>>(&input_data) {
        records = arr;
    } else if let Ok(single) = serde_json::from_str::<RawScrapedRecord>(&input_data) {
        records.push(single);
    } else {
        error!("[Rust Worker] Formato de entrada no válido. No se pudo interpretar JSON.");
        return Err("JSON inválido".into());
    }

    let effective_source_system = resolved_source_system
        .or_else(|| {
            records
                .first()
                .and_then(|r| if r.source_system.trim().is_empty() { None } else { Some(r.source_system.clone()) })
        })
        .unwrap_or_else(|| resolved_institution.clone());

    let effective_spider = resolved_spider
        .unwrap_or_else(|| effective_source_system.to_lowercase());

    let effective_target_table = resolved_target_table.unwrap_or_else(|| {
        let clean_name = effective_source_system.to_lowercase().replace("-", "_");
        format!("{clean_name}__funding_calls")
    });

    let initial_count = records.len();
    info!(
        "[Rust Worker] Stream recibido con {} registros candidatos para validación (Origen: {}, Tabla destino: {}).",
        initial_count, effective_source_system, effective_target_table
    );

    // 2. Filtrado y Validación de Integridad
    let mut validated_records: Vec<RawScrapedRecord> = Vec::new();
    for rec in records {
        if rec.call_code.trim().is_empty() || rec.url.trim().is_empty() {
            warn!(
                "[Filtro Rust] Omitiendo registro con call_code o URL vacía (código: '{}')",
                rec.call_code
            );
            continue;
        }
        validated_records.push(rec);
    }

    info!(
        "[Rust Worker] Validación completada: {} registros válidos conservados ({} descartados).",
        validated_records.len(),
        initial_count - validated_records.len()
    );

    // 3. Clientes de Tika y RustFS S3
    let tika = TikaClient::new(&args.tika_url);
    let s3 = RustFSS3Client::new(&args.s3_endpoint, &args.s3_access_key, &args.s3_secret_key);

    if !args.dry_run {
        let _ = s3.ensure_bucket(&args.bucket).await;
    }

    let now_utc = Utc::now();
    let date_partition = format!(
        "year={}/month={:02}/day={:02}",
        now_utc.format("%Y"),
        now_utc.format("%m"),
        now_utc.format("%d")
    );

    let mut landing_uris: HashMap<String, String> = HashMap::new();
    let mut total_tika_processed = 0;
    let mut assembled_records: Vec<serde_json::Value> = Vec::new();

    // 4. Procesamiento de Documentos Complejos con Apache Tika y Ensamblaje
    for mut rec in validated_records {
        let code = rec.call_code.clone();
        let src_system = if rec.source_system.is_empty() {
            effective_source_system.clone()
        } else {
            rec.source_system.clone()
        };

        let mut enriched_binaries: Vec<BinaryFileItem> = Vec::new();

        if let Some(binaries) = rec.downloaded_binaries.take() {
            for mut b_item in binaries {
                let is_complex = TikaClient::is_complex_document(&b_item.file_extension);

                // Leer bytes del archivo binario
                let mut file_bytes: Vec<u8> = Vec::new();
                if let Some(ref local_p) = b_item.local_path {
                    if Path::new(local_p).exists() {
                        if let Ok(mut f) = File::open(local_p) {
                            let _ = f.read_to_end(&mut file_bytes);
                        }
                    }
                }

                if file_bytes.is_empty() && b_item.raw_bytes_base64.is_some() {
                    // Si viene en base64
                    if let Ok(decoded) = BASE64_STANDARD.decode(
                        b_item.raw_bytes_base64.as_ref().unwrap(),
                    ) {
                        file_bytes = decoded;
                    }
                }

                // Si es un documento complejo y tenemos bytes, enviar a Apache Tika
                if is_complex && !file_bytes.is_empty() {
                    match tika
                        .extract_text(&file_bytes, &b_item.file_name, &b_item.content_type)
                        .await
                    {
                        Ok(extracted_txt) => {
                            total_tika_processed += 1;
                            b_item.extracted_text = Some(extracted_txt.clone());
                            b_item.extracted_by_tika = Some(true);

                            // Persistir texto plano extraído en Processed Zone de RustFS S3
                            if !args.dry_run {
                                let b_hash = &b_item.sha256_hash[..12.min(b_item.sha256_hash.len())];
                                let txt_key = format!(
                                    "processed/{}/{}/{}_{}.txt",
                                    src_system, code, b_hash, b_item.file_name
                                );
                                let _ = s3
                                    .put_object(
                                        &args.bucket,
                                        &txt_key,
                                        extracted_txt.as_bytes(),
                                        "text/plain; charset=utf-8",
                                    )
                                    .await;
                            }
                        }
                        Err(e) => {
                            warn!("[Rust Worker] Tika no pudo procesar {}: {}", b_item.file_name, e);
                            b_item.extracted_by_tika = Some(false);
                        }
                    }
                }

                // Persistir el archivo binario original en RustFS S3 (binaries/)
                if !args.dry_run && !file_bytes.is_empty() {
                    let b_hash = &b_item.sha256_hash[..12.min(b_item.sha256_hash.len())];
                    let bin_key = format!(
                        "binaries/{}/{}/{}_{}",
                        src_system, code, b_hash, b_item.file_name
                    );
                    if let Ok(uri) = s3
                        .put_object(
                            &args.bucket,
                            &bin_key,
                            &file_bytes,
                            &b_item.content_type,
                        )
                        .await
                    {
                        b_item.s3_uri = Some(uri.clone());
                        landing_uris.insert(format!("{}__bin__{}", code, b_item.file_name), uri);
                    }
                }

                // Limpiar campos pesados de memoria antes de serializar a JSON
                b_item.raw_bytes_base64 = None;
                enriched_binaries.push(b_item);
            }
        }

        rec.downloaded_binaries = Some(enriched_binaries);

        // Convertir a JSON final ensamblado
        let mut rec_value = serde_json::to_value(&rec)?;
        let rec_str = serde_json::to_string(&rec_value)?;
        let rec_hash = calculate_sha256(rec_str.as_bytes());
        let rec_hash_short = &rec_hash[..12];

        // Persistir evidencia HTML si existe
        if let Some(ref raw_html) = rec.raw_html {
            if !args.dry_run && !raw_html.is_empty() {
                let html_key = format!(
                    "documents/{}/{}/source_evidence_{}.html",
                    src_system, code, rec_hash_short
                );
                let _ = s3
                    .put_object(
                        &args.bucket,
                        &html_key,
                        raw_html.as_bytes(),
                        "text/html; charset=utf-8",
                    )
                    .await;
            }
        }

        // Persistir payload crudo individual en landing/
        let item_key = format!(
            "landing/{}/raw_payloads/{}/{}_{}.json",
            src_system, date_partition, code, rec_hash_short
        );
        let item_uri = format!("s3://{}/{}", args.bucket, item_key);

        if !args.dry_run {
            let _ = s3
                .put_object(
                    &args.bucket,
                    &item_key,
                    rec_str.as_bytes(),
                    "application/json",
                )
                .await;
        }

        landing_uris.insert(code.clone(), item_uri);
        assembled_records.push(rec_value);
    }

    // 5. Persistir el Batch Manifest final consolidado en RustFS S3
    let batch_key = format!(
        "landing/{}/funding_opportunities/{}/batch_{}.json",
        effective_source_system, date_partition, batch_id
    );
    let batch_uri = format!("s3://{}/{}", args.bucket, batch_key);

    let final_manifest = FinalBatchManifest {
        spider: effective_spider,
        institution_name: resolved_institution.clone(),
        data_product: "opportunity_intelligence".to_string(),
        source_system: effective_source_system.clone(),
        entity_name: "funding_opportunities".to_string(),
        target_table: effective_target_table,
        code_field: "call_code".to_string(),
        batch_id: batch_id.clone(),
        date_partition: date_partition.clone(),
        batch_uri: batch_uri.clone(),
        extracted_at: now_utc.to_rfc3339(),
        processed_at: Utc::now().to_rfc3339(),
        total_records: assembled_records.len(),
        complex_documents_processed_by_tika: total_tika_processed,
        landing_uris: landing_uris.clone(),
        records: assembled_records,
    };

    let manifest_json = serde_json::to_string_pretty(&final_manifest)?;

    if !args.dry_run {
        info!(
            "[Rust Worker -> RustFS] Persistiendo Batch Manifest consolidado: {}",
            batch_uri
        );
        let _ = s3
            .put_object(
                &args.bucket,
                &batch_key,
                manifest_json.as_bytes(),
                "application/json",
            )
            .await;
    }

    let elapsed = start_time.elapsed();
    info!("================================================================================");
    info!("✅ [Rust Worker] Pipeline finalizado exitosamente en {:?}", elapsed);
    info!("   ├─ Lote Batch ID  : {}", batch_id);
    info!("   ├─ Registros      : {}", final_manifest.total_records);
    info!("   ├─ Tika Procesados: {}", total_tika_processed);
    info!("   └─ Manifest URI   : {}", batch_uri);
    info!("================================================================================");

    // Imprimir el manifest resultante a stdout para permitir tuberías con el Loader
    println!("{}", manifest_json);

    Ok(())
}
