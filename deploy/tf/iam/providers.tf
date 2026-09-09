terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}

# Identity resources live only in the tenancy's home region, so this root
# targets it explicitly rather than inheriting the workload region.
provider "oci" {
  config_file_profile = var.oci_profile
  region              = var.home_region
}
