# Rendered by `python manage.py tf` from .env — do not edit by hand.
oci_profile      = "${OCI_PROFILE}"
region           = "${OCI_REGION}"
genai_region     = "${OCI_GENAI_REGION}"
compartment_ocid = "${OCI_COMPARTMENT_OCID}"
label            = "${OCI_LABEL}"

ssh_public_key = "${OCI_SSH_PUBLIC_KEY}"
admin_cidr     = "${OCI_ADMIN_CIDR}"

db_name           = "${DB_NAME}"
db_admin_password = "${DB_PASSWORD}"
wallet_password   = "${DB_WALLET_PASSWORD}"

db_owner_password         = "${DB_OWNER_PASSWORD}"
db_paf_password           = "${DB_PAF_PASSWORD}"
db_backend_password       = "${DB_BACKEND_PASSWORD}"
db_customer_ro_password   = "${DB_CUSTOMER_RO_PASSWORD}"
db_customer_rw_password   = "${DB_CUSTOMER_RW_PASSWORD}"
db_backoffice_ro_password = "${DB_BACKOFFICE_RO_PASSWORD}"

compute_shape    = "${OCI_COMPUTE_SHAPE}"
paf_tarball_path = "${PAF_TARBALL}"
genai_model      = "${GENAI_MODEL}"
