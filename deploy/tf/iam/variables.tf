variable "oci_profile" {
  description = "Profile in ~/.oci/config used for every API call. Must have tenancy-admin rights."
  type        = string
}

variable "region" {
  description = "Tenancy home region."
  type        = string
}

variable "tenancy_ocid" {
  description = "Root compartment. Dynamic groups and their policies live here."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment holding the workload stack. Scopes both the matching rules and the grant."
  type        = string
}

variable "label" {
  description = "Name prefix, matching the workload stack's label."
  type        = string
  default     = "paf-poc"
}
