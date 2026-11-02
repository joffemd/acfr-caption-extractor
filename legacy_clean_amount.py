import re
#from utils import clean_amount as ca
import re
def clean_amount(string):
    #print('string',string)
    if len(string)>0:
        if string[0]=='.':
            string='0'+string
        #print('string',string)
        #if 1==1:
        try:
            string_new=string.replace('.d','.0')
            string_new = re.sub(r"[^\d.,-]", "", string)
            if len(string_new)>0:

                for i in range(len(list(string_new))):
                    list_string = list(string_new)
                    if not list_string[-1].isdigit():
                            list_string[-1]=""
                    elif not list_string[0].isdigit() and (not list_string[0]=='-' or not list_string[1].isdigit()):
                        list_string[0] = ""
                    string_new="".join(list_string)


                string_list = list(string_new)
                # '-' and '=' correction.

                indices = [i for i, x in enumerate(string_list) if x == "-"]

                if len(indices) > 0:
                    if indices[-1] == len(string_list)-3:
                        string_list[indices[-1]] = '='
                    if len(indices) > 1:
                        for i in indices[:-1]:
                            string_list[i] = ""

                string_list = list("".join(string_list))

                check_p = '=' in string_list


                #Correcting ',' and '.'


                if check_p == True:
                    idx = string_list.index('=')
                    if not string_list[idx-3].isdigit() and string_list[idx-3] == ',':
                        string_list[idx-3] = "."
                        indx = [i for i,x in enumerate(string_list[:idx-3]) if x == '.']
                        for i in indx:
                            string_list[i] = ','
                    if not string_list[idx-4].isdigit() and (string_list[idx-4] == '.' or string_list[idx-4]==','):
                        string_list[idx-4] = ','
                        indx = [i for i,x in enumerate(string_list[:idx-2]) if x == '.']
                        for i in indx:
                            string_list[i] = ','            
                else:
                    
                    Negative = False
                    
                    if string_list[0] == '-':
                        rev_str_list = string_list[:0:-1]
                        Negative = True
                    else:
                        rev_str_list = string_list[::-1]
                        
                    def get_NtDigit(rev_str_list):
                        NtDigit_list = []
                        idx = 0
                        for i in rev_str_list:
                            if not i.isdigit():
                                NtDigit_list.append(idx)
                            idx += 1
                        return NtDigit_list

                    NtDigit_list = get_NtDigit(rev_str_list)

                    if len(NtDigit_list) == 1:
                        if NtDigit_list[0] == 2 or NtDigit_list[0] == 1:
                            rev_str_list[NtDigit_list[0]] = '.'
                        elif NtDigit_list[0] == 3 and len(rev_str_list) < 7:
                            rev_str_list[NtDigit_list[0]] = ','
                        elif not NtDigit_list[0] == 2 and NtDigit_list[0] != 3:
                                NtDigit_list[0] = ""
                        elif NtDigit_list[0] == 3 and len(rev_str_list) > 7:
                            rev_str_list[NtDigit_list[0]] = '.'

                    if len(NtDigit_list) > 1:
                        if NtDigit_list[0] == 2 or NtDigit_list[0] == 1:
                            rev_str_list[NtDigit_list[0]] = '.'
                            for i in range(1,len(NtDigit_list)):
                                rev_str_list[NtDigit_list[i]] = ","
                        elif NtDigit_list[0] == 3 and rev_str_list[NtDigit_list[0]] == '.':
                            if NtDigit_list[1] == 6:
                                for i in NtDigit_list:
                                    rev_str_list[i] = ","
                            elif NtDigit_list[1] == 7:
                                for i in range(1,len(NtDigit_list)):
                                    rev_str_list[NtDigit_list[i]] = ","
                        elif NtDigit_list[0] == 3 and rev_str_list[NtDigit_list[0]] == ',':
                            if NtDigit_list[1] == 7:
                                rev_str_list[NtDigit_list[0]] = '.'
                                for i in NtDigit_list[1:]:
                                    rev_str_list[i] = ","
                            else:
                                for i in NtDigit_list:
                                    rev_str_list[i] = ","
                    
                    string_list = rev_str_list[::-1]
                    
                    if Negative == True:
                        string_list.insert(0,'-')
                
                string_new="".join(string_list)
            else:
                string_new=0
        except:
        #else:
            string_new=string
        #print('string',string,'string_new',string_new)
    else:
        string_new=0

    string_new=re.sub('[^0-9.-]', '', str(string_new))
    try:
        string_new_val=float(string_new)
    except:
        string_new=re.sub('[^0-9-]', '', str(string_new))
        if len(string_new)>0:
            string_new=string_new
        else:
            string_new=0.0
    return string_new
