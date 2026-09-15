variable "oci_profile" {
  description = "Profile in ~/.oci/config used for every API call."
  type        = string
}

variable "region" {
  description = "Workload region — VCN, computes, load balancer and ADB."
  type        = string
}

variable "genai_region" {
  description = "Region serving OCI Generative AI. Models are called cross-region when it differs from var.region."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment that owns every resource in this stack."
  type        = string
}

variable "label" {
  description = "Name prefix for every resource, so several stacks can share a compartment."
  type        = string
  default     = "paf-poc"
}

variable "ssh_public_key" {
  description = "Public key installed for the opc user on all computes."
  type        = string
}

variable "vcn_cidr" {
  description = "Address space for the stack's VCN."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "Load balancer and bastion subnet."
  type        = string
  default     = "10.0.1.0/24"
}

variable "private_subnet_cidr" {
  description = "Workload subnet — computes and the ADB private endpoint."
  type        = string
  default     = "10.0.2.0/24"
}

variable "admin_cidr" {
  description = "Source range allowed to reach the bastion over SSH. Set to the operator's own address; there is no safe default."
  type        = string
}

variable "db_name" {
  description = "ADB database name. Letters and digits only, at most 14 characters."
  type        = string
  default     = "pafpoc"
}

variable "db_admin_password" {
  description = "ADB ADMIN password. 12-30 characters, upper, lower, digit, no double quote."
  type        = string
  sensitive   = true
}

variable "db_owner_password" {
  description = "Password for the schema owners. They hold no CREATE SESSION, so it opens nothing."
  type        = string
  sensitive   = true
}

variable "db_paf_password" {
  description = "PAF_PLATFORM password, shared with AAI_RO_PAF_PLATFORM because PAF requires the pair to match."
  type        = string
  sensitive   = true
}

variable "db_backend_password" {
  description = "SVC_BACKEND password — the Application Service's login."
  type        = string
  sensitive   = true
}

variable "db_customer_ro_password" {
  description = "CUSTOMER_AGENT_RO password — CHAT_FLOW's read path."
  type        = string
  sensitive   = true
}

variable "db_customer_rw_password" {
  description = "CUSTOMER_AGENT_RW password — CHAT_FLOW's write path."
  type        = string
  sensitive   = true
}

variable "db_backoffice_ro_password" {
  description = "BACKOFFICE_AGENT_RO password — RESEARCH_WORKFLOW's read path."
  type        = string
  sensitive   = true
}

variable "db_ecpu_count" {
  description = "ECPUs allocated to the ADB instance."
  type        = number
  default     = 2
}

variable "db_storage_tbs" {
  description = "ADB storage in terabytes."
  type        = number
  default     = 1
}

variable "compute_shape" {
  description = "Flex shape used by every workload compute."
  type        = string
  default     = "VM.Standard.E5.Flex"
}

variable "compute_ocpus" {
  description = "OCPUs per workload compute."
  type        = number
  default     = 2
}

variable "compute_memory_gbs" {
  description = "Memory per workload compute."
  type        = number
  default     = 16
}

variable "artefact_base_url" {
  description = "Pre-authenticated request prefix each compute pulls its artefact zip from."
  type        = string
  default     = ""
}

variable "db_version" {
  description = "ADB database version."
  type        = string
  default     = "26ai"
}

variable "wallet_password" {
  description = "Password protecting the generated ADB wallet zip."
  type        = string
  sensitive   = true
}

variable "artifacts_par_expiration_in_days" {
  description = "Lifetime of the read-only PARs each instance fetches its payload through."
  type        = number
  default     = 7
}

variable "paf_tarball_path" {
  description = "Local path to the PAF kit tarball, uploaded once and fetched by the paf tier."
  type        = string

  # Caught at plan time, so a missing kit fails before any resource is touched
  # rather than part-way through an apply.
  validation {
    condition     = fileexists(var.paf_tarball_path)
    error_message = "paf_tarball_path does not exist. Put the X86_64 kit tarball in paf/dist/ and re-run `manage.py tf`."
  }
}

variable "genai_model" {
  description = "OCI Generative AI model the Select AI profiles call."
  type        = string
  default     = "meta.llama-3.3-70b-instruct"
}
