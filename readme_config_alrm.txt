the 3 modes are : arm (always on regardless the time)
                   auto ( alarm is on during arm_start and arm_end)
                   disarm ( disable the alarm)

theses setting must be edited in the esp3_alarm_config.json 
on sam_cloud_1 in google cloud 
make a new file in pythonista on iphone cloud file then
in google cloud dashboard chose upload and overwrite the old config

{
  "mode": "arm",
  "arm_start": 19,
  "arm_end": 9
}

{
  "mode": "auto",
  "arm_start": 19,
  "arm_end": 9
}

{
  "mode": "disarm",
  "arm_start": 19,
  "arm_end": 9
}