# Rendered by `python manage.py tf` from .env — do not edit by hand.
# Identity resources are created in the tenancy's home region, which is not
# necessarily the region the workload runs in.
oci_profile      = "${OCI_PROFILE}"
home_region      = "${OCI_HOME_REGION}"
tenancy_ocid     = "${OCI_TENANCY_OCID}"
compartment_ocid = "${OCI_COMPARTMENT_OCID}"
label            = "${OCI_LABEL}"
