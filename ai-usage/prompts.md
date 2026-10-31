@'

\# Prompt history



Tool used: Claude (claude.ai chat). No other AI tool was used.

Dates: 30 Oct 2026 onward.



Notes:

\- Many of my messages were typed by voice dictation, so they contain grammar and

&#x20; sentence mistakes. I kept them exactly as I sent them.

\- Claude's chat has no prompt export, so I copied my messages by hand.

\- I left out the full text of the recruitment email, the portal page and the problem

&#x20; statement, because the company asked candidates not to share them. They are marked \[omitted].

\- Claude's responses are not included (optional per the FAQ).



\---



\## 1. Round 3 invitation

\[Pasted the Gmail invitation email from YottaFlex AI for the 72-hour coding challenge. Text omitted.]



\## 2. Documents

\[Uploaded two PDFs: "YottaFlex AI Candidate Project Submission Guidelines" and "YottaFlex AI Candidate Project FAQ".]



\## 3. Asking for a simple explanation

Tell me this in understanding way, what they are saying, what I need to do. Completely new to me, explain it clearly, what to do and what are the next steps to complete this project and in efficient way, and what they are asking to me to build. Tell me, what are the projects that I need to build? They given this link, I'll send you, and tell me what are the next steps.https://recruitment.yottaflex.ai/careers/my/application/6157 Give me the content in the humanized way so that I can understand it clearly.



\## 4. Portal page

\[Pasted the text of my application page on the recruitment portal. Text omitted.]





\## 5. Problem statement

\[Pasted the text of the problem statement page. Text omitted.]

This is the problem statement, I think so. After I clicking on that 72 hours coding challenge, and now I'm pasting that what they are usually expecting from me. So study it properly and tell me what they are asking to do and give me the steps how to do that and submit it properly.



\## 6. Asking for an easier explanation

not understand what it is saying. You are saying, just explain it more briefly in understanding way with the humanized content, so that I can understand it well. I can make a note of it, so that I can explain them in understanding way. Tell me and teach me what to do. Explain it the way you are explained to the children.



\## 7. Asking about the project and requirements

Did they give an, for my first question is, did they give an any project to you? Like example, you must do e-commerce website, or you must do something like any website, did they give me? And the second one is, what are their requirements? Tell me in simple way so that I can note it down myself.



\## 8. Choosing the topic

I was selected the bank transactions as the project. So tell me the steps now to complete the project based on their requirements. Tell me what are the steps, how many steps are there to complete the requirement of the project in clean way and an understanding way. I want the steps. Tell me how many steps are there and steps, and if the bank transaction project is good for me and as per their requirements, is it good or not? Tell me.



\## 9. Step 1

step1





\## 10. Git push result

\[Pasted terminal output of a successful git push.]



\## 11. Step 2

give me the step2 with the commands,code which is need to complete the step2



\## 12. Step 2 finished

step 2 done



\## 13. Step 3 output

\[Pasted terminal output of the reproducibility check, git add, commit and push.]

is this ok can i go to next sept



\## 14. Later steps

step 4 done



step 5 done



step6 done



step 7 done



step 8 done





\## 16. This file

Okay, in Notepad, a usage prompts.md. What are the sentences did I need to paste? So are like, give me the complete code so that I can paste it directly.

'@ | Set-Content -Path ai-usage\\prompts.md -Encoding utf8

\##  17.Final checks

\[Pasted terminal output: pytest results (53 passed), performance\_results.md, git commands, and the fresh clone test.]


## 25. Performance investigation
[Pasted the three timing results of the insert-order and cache test.]
shuffled order (like the real file)         2.81 s
sorted by transaction_id                    1.48 s
shuffled order + bigger cache (64 MB)       0.86 s
