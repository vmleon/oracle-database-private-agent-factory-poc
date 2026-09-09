# PAF kit tarballs

Download the Private Agent Factory 26.7 kit from Oracle Software Delivery and
drop the tarball here. The files are ignored by git — only this README is tracked.

One tarball per CPU architecture, and the two deployment targets do not share one:

| Target                        | Architecture | Filename token       |
| ----------------------------- | ------------ | -------------------- |
| Local (Apple Silicon podman)  | ARM64        | `ARM64` or `aarch64` |
| Cloud (`VM.Standard.E5.Flex`) | x86_64       | `x86`, `x86_64` or `amd64` |

The kit spells its architecture differently between builds, so the filename is
matched on any of the tokens above rather than one exact name.

`manage.py setup local` and `manage.py setup cloud` each resolve `PAF_TARBALL`
to the tarball matching their target. On the cloud target Terraform uploads it
to Object Storage, and the `paf` tier fetches it through a read-only
pre-authenticated request — the instance never holds OCI credentials.
