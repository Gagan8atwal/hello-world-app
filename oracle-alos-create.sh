#!/usr/bin/env bash
set -euo pipefail

export OCI_CLI_SUPPRESS_FILE_PERMISSIONS_WARNING=True
export OCI_CLI_REGION=us-phoenix-1

NAME="alos-zero-cost-test"
VCN_NAME="alos-zero-cost-vcn"
SUBNET_NAME="alos-zero-cost-subnet"
REGION="us-phoenix-1"
SHAPE="VM.Standard.A1.Flex"
OCPUS=1
MEM_GB=6
BOOT_GB=50
RESULT="$HOME/alos-oracle-bootstrap-result.json"

log(){ printf '[ALOS-ORACLE] %s\n' "$*"; }
fail(){ printf '[ALOS-ORACLE] BLOCKED: %s\n' "$*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || fail "$1 is required in Oracle Cloud Shell"; }
need oci
need jq

log "Verifying Oracle Cloud Shell identity and Always Free safety bounds"
TENANCY="$(oci iam availability-domain list --region "$REGION" --query 'data[0]."compartment-id"' --raw-output)"
[[ "$TENANCY" == ocid1.tenancy.* ]] || fail "Could not resolve tenancy OCID"
mapfile -t ADS < <(oci iam availability-domain list --region "$REGION" --query 'data[].name' --raw-output | tr -d '[]",' | tr ' ' '\n' | sed '/^$/d')
((${#ADS[@]} > 0)) || fail "No availability domains found in $REGION"

# Always Free A1 post-trial ceiling is 2 OCPUs / 12 GB total. Refuse to create
# if this 1 OCPU / 6 GB host would exceed that ceiling anywhere in the tenancy.
COMP_JSON="$(oci iam compartment list --compartment-id-in-subtree true --access-level ACCESSIBLE --all --region "$REGION")"
mapfile -t COMPS < <(printf '%s' "$COMP_JSON" | jq -r --arg root "$TENANCY" '[ $root ] + [.data[].id] | unique[]')
USED_OCPUS=0
USED_MEM=0
for C in "${COMPS[@]}"; do
  INST="$(oci compute instance list --compartment-id "$C" --all --region "$REGION" 2>/dev/null || printf '{"data":[]}')"
  O="$(printf '%s' "$INST" | jq '[.data[] | select(.shape=="VM.Standard.A1.Flex" and ."lifecycle-state"!="TERMINATED") | (."shape-config".ocpus // 0)] | add // 0')"
  M="$(printf '%s' "$INST" | jq '[.data[] | select(.shape=="VM.Standard.A1.Flex" and ."lifecycle-state"!="TERMINATED") | (."shape-config"."memory-in-gbs" // 0)] | add // 0')"
  USED_OCPUS="$(awk -v a="$USED_OCPUS" -v b="$O" 'BEGIN{print a+b}')"
  USED_MEM="$(awk -v a="$USED_MEM" -v b="$M" 'BEGIN{print a+b}')"
done
awk -v u="$USED_OCPUS" -v n="$OCPUS" 'BEGIN{exit !((u+n)<=2.0001)}' || fail "Existing A1 usage would exceed the Always Free 2-OCPU ceiling"
awk -v u="$USED_MEM" -v n="$MEM_GB" 'BEGIN{exit !((u+n)<=12.0001)}' || fail "Existing A1 usage would exceed the Always Free 12-GB memory ceiling"

# Always Free block-volume pool is 200 GB. Refuse if a new 50-GB boot volume
# could take total known block/boot storage above it.
USED_STORAGE=0
for C in "${COMPS[@]}"; do
  VOLS="$(oci bv volume list --compartment-id "$C" --all --region "$REGION" 2>/dev/null || printf '{"data":[]}')"
  S="$(printf '%s' "$VOLS" | jq '[.data[] | select(."lifecycle-state"!="TERMINATED") | (."size-in-gbs" // 0)] | add // 0')"
  USED_STORAGE="$(awk -v a="$USED_STORAGE" -v b="$S" 'BEGIN{print a+b}')"
  for AD in "${ADS[@]}"; do
    BVS="$(oci bv boot-volume list --compartment-id "$C" --availability-domain "$AD" --all --region "$REGION" 2>/dev/null || printf '{"data":[]}')"
    B="$(printf '%s' "$BVS" | jq '[.data[] | select(."lifecycle-state"!="TERMINATED") | (."size-in-gbs" // 0)] | add // 0')"
    USED_STORAGE="$(awk -v a="$USED_STORAGE" -v b="$B" 'BEGIN{print a+b}')"
  done
done
awk -v u="$USED_STORAGE" -v n="$BOOT_GB" 'BEGIN{exit !((u+n)<=200.0001)}' || fail "Existing block storage plus this boot volume would exceed the 200-GB Always Free pool"

log "Free-tier guard passed: existing A1=${USED_OCPUS} OCPU/${USED_MEM} GB, storage=${USED_STORAGE} GB"

# Reuse an existing dedicated ALOS VCN if this helper was started twice.
VCNS="$(oci network vcn list --compartment-id "$TENANCY" --all --region "$REGION")"
VCN="$(printf '%s' "$VCNS" | jq -r --arg n "$VCN_NAME" '[.data[] | select(."display-name"==$n and ."lifecycle-state"!="TERMINATED")][0].id // empty')"
if [[ -z "$VCN" ]]; then
  log "Creating free VCN"
  VCN="$(oci network vcn create --compartment-id "$TENANCY" --cidr-block 10.240.0.0/16 --display-name "$VCN_NAME" --dns-label alosvcn --region "$REGION" --wait-for-state AVAILABLE --query data.id --raw-output)"
fi
VCN_DATA="$(oci network vcn get --vcn-id "$VCN" --region "$REGION")"
SL="$(printf '%s' "$VCN_DATA" | jq -r '.data."default-security-list-id"')"
RT="$(printf '%s' "$VCN_DATA" | jq -r '.data."default-route-table-id"')"

IGWS="$(oci network internet-gateway list --compartment-id "$TENANCY" --vcn-id "$VCN" --all --region "$REGION")"
IGW="$(printf '%s' "$IGWS" | jq -r '[.data[] | select(."display-name"=="alos-zero-cost-igw" and ."lifecycle-state"!="TERMINATED")][0].id // empty')"
if [[ -z "$IGW" ]]; then
  IGW="$(oci network internet-gateway create --compartment-id "$TENANCY" --vcn-id "$VCN" --is-enabled true --display-name alos-zero-cost-igw --region "$REGION" --wait-for-state AVAILABLE --query data.id --raw-output)"
fi

# Default deny inbound. Outbound is required only for package/bootstrap and OCI agent control-plane traffic.
oci network security-list update --security-list-id "$SL" --ingress-security-rules '[]' --egress-security-rules '[{"destination":"0.0.0.0/0","protocol":"all","isStateless":false}]' --force --region "$REGION" >/dev/null
oci network route-table update --rt-id "$RT" --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW\"}]" --force --region "$REGION" >/dev/null

SUBS="$(oci network subnet list --compartment-id "$TENANCY" --vcn-id "$VCN" --all --region "$REGION")"
SUBNET="$(printf '%s' "$SUBS" | jq -r --arg n "$SUBNET_NAME" '[.data[] | select(."display-name"==$n and ."lifecycle-state"!="TERMINATED")][0].id // empty')"
if [[ -z "$SUBNET" ]]; then
  log "Creating free public subnet with zero inbound rules"
  SUBNET="$(oci network subnet create --compartment-id "$TENANCY" --vcn-id "$VCN" --cidr-block 10.240.1.0/24 --display-name "$SUBNET_NAME" --dns-label alossub --prohibit-public-ip-on-vnic false --route-table-id "$RT" --security-list-ids "[\"$SL\"]" --region "$REGION" --wait-for-state AVAILABLE --query data.id --raw-output)"
fi

# Reuse an existing live instance with our exact display name if present.
ROOT_INST="$(oci compute instance list --compartment-id "$TENANCY" --all --region "$REGION")"
INSTANCE="$(printf '%s' "$ROOT_INST" | jq -r --arg n "$NAME" '[.data[] | select(."display-name"==$n and ."lifecycle-state"!="TERMINATED")][0].id // empty')"

if [[ -z "$INSTANCE" ]]; then
  IMAGES="$(oci compute image list --compartment-id "$TENANCY" --shape "$SHAPE" --all --sort-by TIMECREATED --sort-order DESC --region "$REGION")"
  IMAGE="$(printf '%s' "$IMAGES" | jq -r '[.data[] | select(."operating-system"=="Canonical Ubuntu" and (."operating-system-version"|tostring|startswith("24.04")))][0].id // empty')"
  [[ "$IMAGE" == ocid1.image.* ]] || fail "No Ubuntu 24.04 ARM image found for A1"

  USER_DATA="$(printf '%s' '#cloud-config
package_update: false
write_files:
  - path: /etc/alos-cloud-test
    owner: root:root
    permissions: "0644"
    content: |
      ALOS Oracle founder-independent test host
runcmd:
  - [ bash, -lc, "systemctl enable --now oracle-cloud-agent || true" ]
' | base64 -w0)"

  log "Launching 1-OCPU / 6-GB A1 test host (within Always Free post-trial limits)"
  LAST_ERR=""
  for AD in "${ADS[@]}"; do
    set +e
    OUT="$(oci compute instance launch --availability-domain "$AD" --compartment-id "$TENANCY" --shape "$SHAPE" --shape-config '{"ocpus":1,"memoryInGBs":6}' --image-id "$IMAGE" --subnet-id "$SUBNET" --assign-public-ip true --boot-volume-size-in-gbs "$BOOT_GB" --display-name "$NAME" --metadata "{\"user_data\":\"$USER_DATA\"}" --freeform-tags '{"ALOS":"zero-cost-test","CostBoundary":"always-free"}' --region "$REGION" 2>&1)"
    RC=$?
    set -e
    if [[ $RC -eq 0 ]]; then
      INSTANCE="$(printf '%s' "$OUT" | jq -r '.data.id')"
      break
    fi
    LAST_ERR="$OUT"
    log "A1 capacity unavailable in $AD; trying next availability domain"
  done
  [[ "$INSTANCE" == ocid1.instance.* ]] || fail "Could not launch A1 in any Phoenix AD. Last error: ${LAST_ERR:0:500}"
else
  log "Reusing existing $NAME instance"
fi

log "Waiting for instance RUNNING"
oci compute instance get --instance-id "$INSTANCE" --region "$REGION" --wait-for-state RUNNING --max-wait-seconds 900 >/dev/null
VNIC="$(oci compute vnic-attachment list --compartment-id "$TENANCY" --instance-id "$INSTANCE" --all --region "$REGION" --query 'data[0]."vnic-id"' --raw-output)"
PUBLIC_IP="$(oci network vnic get --vnic-id "$VNIC" --region "$REGION" --query 'data."public-ip"' --raw-output)"
STATE="$(oci compute instance get --instance-id "$INSTANCE" --region "$REGION" --query 'data."lifecycle-state"' --raw-output)"

jq -n --arg instanceId "$INSTANCE" --arg state "$STATE" --arg publicIp "$PUBLIC_IP" --arg region "$REGION" --arg shape "$SHAPE" --argjson ocpus "$OCPUS" --argjson memoryGb "$MEM_GB" '{result:"created-or-reused",instanceId:$instanceId,state:$state,publicIp:$publicIp,region:$region,shape:$shape,ocpus:$ocpus,memoryGb:$memoryGb,bootGb:50,costBoundary:"Oracle Always Free post-trial ceiling",paidFallback:false}' | tee "$RESULT"
log "SUCCESS. Result saved to $RESULT"
log "No inbound security rules were opened. Next step: manage the host through Oracle Cloud Agent / Run Command and install the sealed ALOS test payload."
